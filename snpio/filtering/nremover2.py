import sys
import os
from pathlib import Path
import warnings
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from Bio.Align import MultipleSeqAlignment
from Bio.Seq import Seq
from Bio import SeqUtils
from copy import deepcopy

from ..plotting.plotting import Plotting


class NRemover2:
    """
    A class for filtering alignments based on the proportion of missing data in a genetic alignment. The class can filter out sequences (samples) and loci (columns) that exceed a missing data threshold. The loci can be filtered by global missing data proportions or if any given population exceeds the missing data threshold. A number of informative plots are also generated.

    Attributes:
        alignment (list of Bio.SeqRecord.SeqRecord): The input alignment to filter.
        populations (list of str): The population for each sequence in the alignment.

    Methods:
        filter_missing: Filters out sequences from the alignment that have more than a given proportion of missing data.
        filter_missing_pop: Filters out sequences from the alignment that have more than a given proportion of missing data in a specific population.
        filter_missing_sample: Filters out samples from the alignment that have more than a given proportion of missing data.
        filter_monomorphic: Filters out monomorphic sites.
        filter_singletons: Filters out loci (columns) where the only variant is a singleton.
        get_population_sequences: Returns the sequences for a specific population.
        count_iupac_alleles: Counts the number of occurrences of each IUPAC ambiguity code in a given column.
        count_unique_bases: Counts the number of unique bases in a given column.
        filter_singletons_sfs: Filters out singletons for the site frequency spectrum (SFS).
        plot_missing_data_thresholds: Plots the proportion of missing data against the filtering thresholds.
        print_filtering_report: Prints a summary of the filtering results.
        print_cletus: Prints ASCII art of Cletus (a silly inside joke).
    """

    def __init__(self, popgenio):
        """
        Initialize the NRemover class using an instance of the PopGenIO class.

        Args:
            popgenio (PopGenIO): An instance of the PopGenIO class containing the genetic data alignment, population map, and populations.
        """
        self._msa = popgenio.alignment
        self._alignment = deepcopy(self._msa)
        self.popgenio = popgenio
        self.popmap = popgenio.popmap
        self.popmap_inverse = popgenio.popmap_inverse
        self.populations = list(set(popgenio.populations))
        self.poplist = popgenio.populations

    def nremover(
        self,
        max_missing_global=1.0,
        max_missing_pop=1.0,
        max_missing_sample=1.0,
        min_maf=0.0,
        biallelic=False,
        monomorphic=False,
        singletons=False,
        plot_missingness_report=True,
        plot_outfile="missingness_report.png",
        suppress_cletus=False,
        plot_dir="plots",
        included_steps=None,
    ):
        if not suppress_cletus:
            self.print_cletus()

        self.alignment = self.msa[:]
        aln_before = deepcopy(self.alignment)

        if plot_missingness_report:
            self.plot_missing_data_thresholds(plot_outfile, plot_dir=plot_dir)

        steps = [
            (
                "Filter monomorphic sites",
                monomorphic,
                monomorphic,
                self.filter_monomorphic,
                0,
            ),
            (
                "Filter singletons",
                singletons,
                singletons,
                self.filter_singletons,
                1,
            ),
            (
                "Filter non-biallelic sites",
                biallelic,
                biallelic,
                self.filter_non_biallelic,
                2,
            ),
            (
                "Filter missing data (global)",
                max_missing_global < 1.0,
                max_missing_global,
                self.filter_missing,
                3,
            ),
            (
                "Filter missing data (population)",
                max_missing_pop < 1.0,
                max_missing_pop,
                self.filter_missing_pop,
                4,
            ),
            (
                "Filter missing data (sample)",
                max_missing_sample < 1.0,
                max_missing_sample,
                self.filter_missing_sample,
                5,
            ),
            (
                "Filter minor allele frequency",
                min_maf > 0.0,
                min_maf,
                self.filter_minor_allele_frequency,
                6,
            ),
        ]

        loci_removed_per_step = []

        for name, condition, threshold, filter_func, step_idx in steps:
            if condition:
                filtered_alignment = filter_func(
                    threshold, alignment=self.alignment
                )
                loci_removed = len(self.alignment[0]) - len(
                    filtered_alignment[0]
                )

                if name != "Filter missing data (sample)":
                    loci_removed_per_step.append((name, loci_removed))
                    self.alignment = filtered_alignment
            else:
                loci_removed_per_step.append((name, 0))

        aln_after = deepcopy(self.alignment)

        self.print_filtering_report(
            aln_before, aln_after, loci_removed_per_step
        )

        if included_steps is None:
            included_steps = [
                step_idx for _, condition, _, _, step_idx in steps if condition
            ]

        Plotting.plot_sankey_filtering_report(
            loci_removed_per_step,
            len(aln_before[0]),
            len(aln_after[0]),
            "sankey_filtering_report.html",
            plot_dir=plot_dir,
            included_steps=included_steps,
        )

        self.popgenio.filtered_alignment = self.alignment
        return self.popgenio

    def filter_missing(self, threshold, alignment=None, return_props=False):
        """
        Filters out columns with missing data proportion greater than the given threshold.

        Args:
            threshold (float): The maximum missing data proportion allowed.
            alignment (MultipleSeqAlignment, optional): The alignment to be filtered. Defaults to the stored alignment.
            return_props (bool, optional): Whether to return the mean missing data proportion among all columns after filtering. Defaults to False.

        Returns:
            MultipleSeqAlignment: The filtered alignment.

        Raises:
            TypeError: If threshold is not a float value.
            ValueError: If threshold is not between 0.0 and 1.0 inclusive.
        """
        if alignment is None:
            alignment = self.alignment

        alignment_array = alignment

        # alignment_array = np.array(
        #     [list(str(record.seq)) for record in alignment]
        # )
        missing_counts = np.sum(alignment_array == "N", axis=0)
        mask = missing_counts / alignment_array.shape[0] <= threshold

        # Apply the mask to filter out columns with a missing proportion greater than the threshold
        filtered_alignment_array = alignment_array[:, mask]

        new_missing_counts = np.sum(filtered_alignment_array == "N", axis=0)

        # Calculate the mean missing data proportion among all the columns
        missing_prop = new_missing_counts / filtered_alignment_array.shape[0]

        std_missing_prop = np.std(
            new_missing_counts / filtered_alignment_array.shape[0]
        )

        if return_props:
            return (
                filtered_alignment_array,
                missing_prop,
                std_missing_prop,
            )
        else:
            return filtered_alignment_array

    def filter_missing_pop(
        self, max_missing, alignment, populations=None, return_props=False
    ):
        if populations is None:
            populations = self.popmap_inverse

        alignment_array = alignment

        # alignment_array = np.array(
        #     [list(str(record.seq)) for record in alignment]
        # )

        sample_id_to_index = {
            record.id: i for i, record in enumerate(self.msa)
        }

        def missing_data_proportion(column, indices):
            missing_count = sum(
                column[i] in {"N", "-", ".", "?"} for i in indices
            )
            return missing_count / len(indices)

        def exceeds_threshold(column):
            missing_props = {}
            flaglist = []
            for pop, sample_ids in populations.items():
                indices = [
                    sample_id_to_index[sample_id] for sample_id in sample_ids
                ]
                missing_prop = missing_data_proportion(column, indices)

                if missing_prop >= max_missing:
                    flagged = True
                else:
                    missing_props[pop] = missing_prop
                    flagged = False
                flaglist.append(flagged)
            return flaglist, missing_props

        mask_and_missing_props = np.array(
            [exceeds_threshold(col) for col in alignment_array.T], dtype=object
        )
        mask = np.all(
            np.array([mmp[0] for mmp in mask_and_missing_props], dtype=bool),
            axis=1,
        )

        mean_missing_props = [mmp[1] for mmp in mask_and_missing_props]

        key_values = {
            key: [
                d.get(key)
                for d in mean_missing_props
                if d.get(key) is not None
            ]
            for key in set().union(*mean_missing_props)
        }

        missing_props = {k: v for k, v in key_values.items()}
        std_missing_props = {k: np.std(v) for k, v in key_values.items()}

        filtered_alignment_array = alignment_array[:, ~mask]

        if return_props:
            return (
                filtered_alignment_array,
                missing_props,
                std_missing_props,
            )
        else:
            return filtered_alignment_array

    def filter_missing_sample(
        self, threshold, alignment=None, return_props=False
    ):
        """
        Filters out sequences with missing data proportion greater than the given threshold.

        Args:
            threshold (float): The maximum missing data proportion allowed for each sequence.
            alignment (MultipleSeqAlignment, optional): The alignment to be filtered. Defaults to the stored alignment.
            return_props (bool, optional): Whether to return the mean missing data proportion among all sequences after filtering. Defaults to False.

        Returns:
            MultipleSeqAlignment: The filtered alignment.

        Raises:
            TypeError: If threshold is not a float value.
            ValueError: If threshold is not between 0.0 and 1.0 inclusive.
        """

        if alignment is None:
            alignment = self.alignment

        alignment_array = alignment

        # alignment_array = np.array(
        #     [list(str(record.seq)) for record in alignment]
        # )
        missing_counts = np.sum(alignment_array == "N", axis=1)
        mask = missing_counts / alignment_array.shape[1] <= threshold

        # Apply the mask to filter out sequences with a missing proportion greater than the threshold
        filtered_alignment_array = alignment_array[mask, :]

        new_missing_counts = np.sum(filtered_alignment_array == "N", axis=1)

        # Calculate the mean missing data proportion among all the sequences
        missing_prop = new_missing_counts / filtered_alignment_array.shape[1]

        # Get the indices of the True values in the mask
        mask_indices = [i for i, val in enumerate(mask) if val]

        # Convert the filtered alignment array back to a list of SeqRecord objects
        filtered_alignment = [
            filtered_alignment_array[i, :]
            for i, index in enumerate(mask_indices)
        ]

        if return_props:
            return filtered_alignment, missing_prop, mask_indices
        else:
            return filtered_alignment

    def filter_minor_allele_frequency(
        self, min_maf, alignment=None, return_props=False
    ):
        if alignment is None:
            alignment = self.alignment
        alignment_array = alignment

        def count_bases(column):
            base_count = {
                "A": 0,
                "C": 0,
                "G": 0,
                "T": 0,
            }
            for base in column:
                if base in base_count:
                    base_count[base] += 1
                elif base not in {"N", "-", "."}:
                    try:
                        ambig_bases = SeqUtils.IUPACData.ambiguous_dna_values[
                            base
                        ]
                        for ambig_base in ambig_bases:
                            base_count[ambig_base] += 1
                    except KeyError:
                        pass
            return base_count

        def minor_allele_frequency(column):
            counts = count_bases(column)
            # Remove counts of "N", "-", and "." characters from the counts dictionary
            counts = {
                base: count
                for base, count in counts.items()
                if base not in {"N", "-", "."}
            }

            if not counts or all(v == 0 for v in counts.values()):
                return 0

            # Sort the counts by their values
            sorted_counts = sorted(counts.values(), reverse=True)
            total = sum(sorted_counts)

            # Calculate the frequencies of each allele
            freqs = [count / total for count in sorted_counts]

            # Return the frequency of the second most common allele (the minor allele)
            return freqs[1] if len(freqs) > 1 else 0

        maf = np.apply_along_axis(minor_allele_frequency, 0, alignment_array)
        mask = maf >= min_maf
        filtered_alignment_array = alignment_array[:, mask]

        new_missing_counts = np.sum(
            np.isin(filtered_alignment_array, ["N", "-", ".", "?"]), axis=0
        )

        # Calculate the mean missing data proportion among all the columns
        missing_prop = new_missing_counts / filtered_alignment_array.shape[0]

        if return_props:
            return (
                filtered_alignment_array,
                missing_prop,
                maf,
            )
        else:
            return filtered_alignment_array

    def filter_non_biallelic(self, threshold=None, alignment=None):
        """
        Filters out loci (columns) that are not biallelic.

        Args:
            threshold (None, optional): Not used.
            alignment (MultipleSeqAlignment, optional): The alignment to be filtered. Defaults to the stored alignment.

        Returns:
            MultipleSeqAlignment: The filtered alignment.
        """

        if alignment is None:
            alignment = self.alignment

        # Convert the input alignment to a numpy array of sequences
        alignment_array = alignment

        iupac = {
            "R": ("A", "G"),
            "Y": ("C", "T"),
            "S": ("G", "C"),
            "W": ("A", "T"),
            "K": ("G", "T"),
            "M": ("A", "C"),
        }

        def count_unique_bases(column):
            """
            Args:
                column (str): A column of bases from an alignment.

            Returns:
                int: The number of unique bases in the column, excluding ambiguous and missing bases.
            """
            base_count = {
                "A": 0,
                "C": 0,
                "G": 0,
                "T": 0,
                "U": 0,
            }

            for base in column:
                if base in base_count:
                    base_count[base] += 1
                elif base in iupac:
                    base1, base2 = iupac[base]
                    base_count[base1] += 1
                    base_count[base2] += 1
                # Ignore "N", "-", and "." bases

            return len([count for count in base_count.values() if count > 0])

        unique_base_counts = np.apply_along_axis(
            count_unique_bases, 0, alignment_array
        )
        mask = unique_base_counts == 2

        # Apply the mask to filter non-biallelic columns
        filtered_alignment_array = alignment_array[:, mask]

        # Convert the filtered alignment array back to a list of SeqRecord objects
        # filtered_alignment = [
        #     SeqRecord(
        #         Seq("".join(filtered_alignment_array[i, :])),
        #         id=original_record.id,
        #         description=original_record.description,
        #     )
        #     for i, original_record in enumerate(alignment)
        # ]

        return filtered_alignment_array

    def count_iupac_alleles(self, column):
        """
        Counts the number of occurrences of each IUPAC ambiguity code in a column of nucleotide sequences.

        Args:
            column (str): A string representing a column of nucleotide sequences.

        Returns:
            dict: A dictionary with the counts of the unambiguous nucleotide bases.
        """
        iupac = {
            "A": "A",
            "C": "C",
            "G": "G",
            "T": "T",
            "U": "T",
            "R": "AG",
            "Y": "CT",
            "S": "GC",
            "W": "AT",
            "K": "GT",
            "M": "AC",
            "B": "CGT",
            "D": "AGT",
            "H": "ACT",
            "V": "ACG",
            "N": "ACGT",
        }

        counts = {"A": 0, "C": 0, "G": 0, "T": 0}

        for base in column:
            if base in iupac:
                for allele in iupac[base]:
                    counts[allele] += 1

        return counts

    def filter_monomorphic(self, threshold=None, alignment=None):
        """
        Filters out monomorphic sites from an alignment.

        Args:
            alignment (Bio.Align.MultipleSeqAlignment): The alignment to be filtered.

        Returns:
            filtered_alignment (Bio.Align.MultipleSeqAlignment): The filtered alignment.
        """

        if alignment is None:
            alignment = self.alignment

        def is_monomorphic(column):
            """
            Determines if a column in an alignment is monomorphic.

            Args:
            - column: a list of bases representing a column in an alignment

            Returns:
            - A boolean indicating whether the column is monomorphic.
            """
            column_list = column.tolist()
            alleles = set(column_list)

            # Remove any ambiguity code
            alleles.discard("N")

            # Count the number of valid alleles
            valid_alleles = [allele for allele in alleles if allele != "-"]

            return len(valid_alleles) <= 1

        alignment_array = alignment.astype(str)

        if alignment_array.shape[1] > 0:
            mask = np.apply_along_axis(is_monomorphic, 0, alignment_array)
            filtered_alignment_array = alignment_array[:, ~mask]
        else:
            filtered_alignment_array = alignment_array

        return filtered_alignment_array

        # filtered_records = [
        #     SeqRecord(Seq("".join(seq_list)), id=rec.id)
        #     for rec, seq_list in zip(alignment, filtered_alignment_array)
        # ]
        # return MultipleSeqAlignment(filtered_records)

    @staticmethod
    def resolve_ambiguity(base):
        """
        Resolves an IUPAC ambiguity code to the set of possible nucleotides it represents.

        Args:
            base (str): A single IUPAC character.

        Returns:
            set: A set of possible nucleotides represented by the IUPAC character.
        """
        iupac_dict = {
            "A": {"A"},
            "C": {"C"},
            "G": {"G"},
            "T": {"T"},
            "U": {"T"},
            "R": {"A", "G"},
            "Y": {"C", "T"},
            "S": {"G", "C"},
            "W": {"A", "T"},
            "K": {"G", "T"},
            "M": {"A", "C"},
            "B": {"C", "G", "T"},
            "D": {"A", "G", "T"},
            "H": {"A", "C", "T"},
            "V": {"A", "C", "G"},
            "N": {"A", "C", "G", "T"},
            "-": {"-"},
        }
        return iupac_dict.get(base.upper(), {"N"})

    def filter_singletons(self, threshold=None, alignment=None):
        """
        Filters out singletons from an alignment.

        Args:
            alignment (Bio.Align.MultipleSeqAlignment): The alignment to be filtered.

        Returns:
            filtered_alignment (Bio.Align.MultipleSeqAlignment): The filtered alignment.
        """

        if alignment is None:
            alignment = self.alignment

        def is_singleton(column):
            """
            Determines if a column in an alignment is a singleton.

            Args:
            - column: a list of bases representing a column in an alignment

            Returns:
            - A boolean indicating whether the column is a singleton, meaning that there is only one
            variant in the column and it appears only once.
            """
            column_list = column.tolist()
            alleles = {
                allele for allele in column_list if allele not in ["N", "-"]
            }
            allele_count = {
                allele: column_list.count(allele) for allele in alleles
            }

            if len(alleles) == 2:
                min_allele = min(alleles, key=lambda x: allele_count[x])
                return allele_count[min_allele] == 1
            return False

        alignment_array = alignment.astype(str)

        if alignment_array.shape[1] > 0:
            mask = np.apply_along_axis(is_singleton, 0, alignment_array)
            filtered_alignment_array = alignment_array[:, ~mask]
        else:
            filtered_alignment_array = alignment_array

        return filtered_alignment_array

        # filtered_records = [
        #     SeqRecord(Seq("".join(seq_list)), id=rec.id)
        #     for rec, seq_list in zip(alignment, filtered_alignment_array)
        # ]
        # return MultipleSeqAlignment(filtered_records)

    def get_population_sequences(self, population):
        """
        Returns a list of sequence strings for a specific population.

        Args:
        - population: str, the name of the population to retrieve sequences for.

        Returns:
        - population_sequences: list, a list of sequence strings for the specified population.

        Raises:
        - ValueError: If the specified population is not found in the object's list of populations.
        """
        population_indices = [
            i for i, pop in enumerate(self.populations) if pop == population
        ]
        alignment_array = self.alignment
        population_sequences = alignment_array[population_indices, :]
        return population_sequences.tolist()

    @staticmethod
    def print_filtering_report(
        before_alignment, after_alignment, loci_removed_per_step
    ):
        """
        Args:
            before_alignment (list): The original alignment before filtering.
            after_alignment (list): The alignment after filtering.
            loci_removed_per_step (list of tuples): A list of tuples, where each tuple contains the name of a filtering step and the number of loci removed during that step.

        Returns:
            None.

        Raises:
            ValueError: If there is no data left after filtering, which could indicate an issue with the filtering or with the provided filtering parameters.

        Note:
            The function also raises a warning if none of the filtering arguments were changed from their defaults, in which case the alignment will not be filtered.
        """
        num_loci_before = len(before_alignment[0])
        num_samples_before = len(before_alignment)
        num_loci_after = len(after_alignment[0])
        num_samples_after = len(after_alignment)
        samples_removed = num_samples_before - num_samples_after

        def missing_data_percent(msa):
            total = len(msa) * len(msa[0])
            if total == 0:
                # for name, loci_removed in loci_removed_per_step:
                #     print(f"  {name}: {loci_removed}")
                raise ValueError(
                    "There is no data left after filtering. This can indicate an issue with the filtering or with the provided filtering parameters."
                )
            missing = np.sum(msa == "N")
            return (missing / total) * 100

        missing_data_before = missing_data_percent(before_alignment)
        missing_data_after = missing_data_percent(after_alignment)

        print("Filtering Report:")
        print(f"  Loci before filtering: {num_loci_before}")
        print(f"  Samples before filtering: {num_samples_before}")

        if (
            all([x[1] == 0 for x in loci_removed_per_step])
            and samples_removed == 0
            and missing_data_before == missing_data_after
        ):
            warnings.warn(
                "The alignment was unchanged. Note that if none of the filtering arguments were changed from defaults, the alignment will not be filtered."
            )

        for name, loci_removed in loci_removed_per_step:
            print(f"  {name}: {loci_removed}")
        print(f"  Samples removed: {samples_removed}")
        print(f"  Loci remaining: {num_loci_after}")
        print(f"  Samples remaining: {num_samples_after}")
        print(f"  Missing data before filtering: {missing_data_before:.2f}%")
        print(f"  Missing data after filtering: {missing_data_after:.2f}%")

    def plot_missing_data_thresholds(
        self,
        output_file,
        num_thresholds=5,
        num_maf_thresholds=5,
        max_maf_threshold=0.1,
        show=False,
        plot_dir="plots",
    ):
        thresholds = np.linspace(0.1, 1, num=num_thresholds)
        maf_thresholds = np.linspace(
            0.0, max_maf_threshold, num=num_maf_thresholds, endpoint=True
        )
        sample_missing_data_proportions = []
        global_missing_data_proportions = []
        population_missing_data_proportions = []
        maf_per_threshold = []
        maf_props_per_threshold = []
        data = []
        mask_indices = []

        for threshold, maf_threshold in zip(thresholds, maf_thresholds):
            mask_idx, sample_missing_prop = self.filter_per_threshold(
                self.filter_missing_sample,
                threshold,
                self.alignment,
                return_props=True,
                is_maf=True,
            )

            global_missing_prop = self.filter_per_threshold(
                self.filter_missing,
                threshold,
                self.alignment,
                return_props=True,
            )

            pop_missing_props = self.filter_per_threshold(
                self.filter_missing_pop,
                threshold,
                self.alignment,
                populations=self.popmap_inverse,
                return_props=True,
            )

            # Get MAF for each threshold
            maf_freqs, maf_props = self.filter_per_threshold(
                self.filter_minor_allele_frequency,
                maf_threshold,
                self.alignment,
                is_maf=True,
                return_props=True,
            )

            sample_missing_data_proportions.append(sample_missing_prop)
            global_missing_data_proportions.append(global_missing_prop)
            population_missing_data_proportions.append(pop_missing_props)
            maf_per_threshold.append(maf_freqs)
            maf_props_per_threshold.append(maf_props)
            mask_indices.append(mask_idx)

        def generate_df(props, thresholds, dftype):
            flattened_proportions = []
            flattened_thresholds = []

            for threshold, array in zip(thresholds, props):
                flattened_proportions.extend(array)
                flattened_thresholds.extend([f"{threshold:.2f}"] * len(array))

            df = pd.DataFrame(
                {
                    "Threshold": flattened_thresholds,
                    "Proportion": flattened_proportions,
                    "Type": dftype,
                }
            )
            return df

        def generate_population_df(props, thresholds):
            df_list = []
            for threshold, prop_dict in zip(thresholds, props):
                for population, proportions in prop_dict.items():
                    temp_df = pd.DataFrame(
                        {
                            "Threshold": [f"{threshold:.2f}"]
                            * len(proportions),
                            "Proportion": proportions,
                            "Type": [population] * len(proportions),
                        }
                    )
                    df_list.append(temp_df)

            df = pd.concat(df_list, ignore_index=True)
            return df

        pops = [
            x
            for indices in mask_indices
            for i, x in enumerate(self.poplist)
            if i in indices
        ]

        df_sample = generate_df(
            sample_missing_data_proportions, thresholds, "Sample"
        )

        df_global = generate_df(
            global_missing_data_proportions, thresholds, "Global"
        )

        df_populations = generate_population_df(
            population_missing_data_proportions, thresholds
        )

        df_maf = generate_df(maf_props_per_threshold, maf_thresholds, "MAF")

        df_mono = generate_df()

        # combine the two dataframes
        df = pd.concat([df_sample, df_global])

        # plot the boxplots
        fig, axs = plt.subplots(3, 2, figsize=(48, 27))
        ax1 = sns.boxplot(
            x="Threshold", y="Proportion", hue="Type", data=df, ax=axs[0, 0]
        )

        ax2 = sns.boxplot(
            x="Threshold",
            y="Proportion",
            hue="Type",
            data=df_populations,
            ax=axs[0, 1],
        )

        ax3 = sns.lineplot(
            x="Threshold", y="Proportion", hue="Type", data=df, ax=axs[1, 0]
        )

        ax4 = sns.lineplot(
            x="Threshold",
            y="Proportion",
            hue="Type",
            data=df_populations,
            ax=axs[1, 1],
        )

        ax5 = sns.violinplot(
            x="Threshold",
            y="Proportion",
            hue="Type",
            data=df,
            inner="box",
            ax=axs[2, 0],
        )

        ax6 = sns.violinplot(
            x="Threshold",
            y="Proportion",
            hue="Type",
            data=df_populations,
            inner="quartile",
            ax=axs[2, 1],
        )

        def make_labs(ax, title, fontsize=28, ticksize=20, loc="upper left"):
            ax.set_title(title, fontsize=fontsize)
            ax.set_xlabel("Missing Data Threshold", fontsize=fontsize)
            ax.set_ylabel("Proportion of Missing Data", fontsize=fontsize)
            ax.set_ylim(0, 1)
            ax.tick_params(axis="both", labelsize=ticksize)
            ax.legend(fontsize=fontsize, loc=loc)

        titles = [
            "Global and Sample Filtering",
            "Per-population Filtering",
        ]

        titles.extend([""] * 4)

        for title, ax in zip(titles, [ax1, ax2, ax3, ax4, ax5, ax6]):
            make_labs(ax, title)

        plt.tight_layout()

        outfile = os.path.join(plot_dir, output_file)
        Path(plot_dir).mkdir(parents=True, exist_ok=True)

        fig.savefig(outfile, facecolor="white")

        if show:
            plt.show()

        plt.close()

        # Plot the MAF visualizations in a separate figure
        fig_maf, axs_maf = plt.subplots(3, 2, figsize=(24, 24))

        for i, (maf, props) in enumerate(
            zip(maf_per_threshold, maf_props_per_threshold)
        ):
            threshold = maf_thresholds[i]

            plt.sca(axs_maf[0, 0])
            Plotting.histogram_maf(maf)

            plt.sca(axs_maf[0, 1])
            Plotting.cdf_maf(maf)

            plt.sca(axs_maf[1, 0])
            Plotting.boxplot_maf(df_maf)

            plt.sca(axs_maf[1, 1])
            Plotting.scatterplot_maf(df_maf)

        plt.sca(axs_maf[2, 0])
        Plotting.lineplot_maf(df_maf)

        plt.sca(axs_maf[2, 1])
        Plotting.cdf_maf(
            props,
            title="Cumulative Missing Data (MAF)",
            ylab="Cumulative Missing Proportion",
        )

        plt.tight_layout()

        # Save the MAF figure
        outfile_maf = os.path.join(plot_dir, f"maf_{output_file}")
        fig_maf.savefig(outfile_maf, facecolor="white")

    def filter_per_threshold(self, filter_func, *args, is_maf=False, **kwargs):
        _, props, freqs = filter_func(*args, **kwargs)
        res = (freqs, props) if is_maf else props
        return res

    @property
    def alignment(self):
        if isinstance(self._alignment, MultipleSeqAlignment):
            a = np.array([list(str(record.seq)) for record in self._alignment])
        else:
            a = self._alignment
        return a

    @alignment.setter
    def alignment(self, value):
        if isinstance(value, MultipleSeqAlignment):
            self._alignment = np.array(
                [list(str(record.seq)) for record in value]
            )
        else:
            self._alignment = value

    @property
    def msa(self):
        return self._msa

    @msa.setter
    def msa(self, value):
        self._msa = value

    @property
    def population_sequences(self):
        """
        Returns a dictionary of population sequences.

        The dictionary keys are the names of the populations, and the values are
        the corresponding sequences for each population. Sequences are in the form
        of a list of strings, where each string is a sequence for a given sample.

        Returns:
            dict: A dictionary of population sequences, where each key is the name
            of a population and the corresponding value is a list of sequences.
        """
        population_sequences = {}
        for population_name in self.populations:
            population_sequences[
                population_name
            ] = self.get_population_sequences(population_name)
        return population_sequences

    @classmethod
    def print_cletus(cls):
        """Prints ASCII art of Cletus from the Simpsons (silly inside joke)."""
        # ASCII Cletus
        cletus_ascii = r"""
                                                      T                                            
                                                     M                                             
                                              +MI   :                                              
                                                  ?.M ?MM888DMD,                                   
                                                   M88888888888888DN.                              
                                                 M88888888888888888888N~                           
                                                8888888888888888888888888M                         
                                              ,88888888888888888888888888888O                      
                                             .88888888888888888888888888888888M                    
                                            =88888888888888888888888888888888888M                  
                                           M88888888888888888888888888888888888888M                
                                         D888888888N88888888888888888888888888888888O              
                                             M8888MID888888888888888888888888N8888888D             
                                            M8888MIIM8888M8888888888888888888MIIMD8888D.           
                                           7888MDIIIM888MII888888888888888888IIIIIN ~M8M           
                                           = IIIIIID88TTIIIM888DI8888M888888?IIIIIII.              
                                             MIIIMIIMIIIII?M88M ,888IIMDIDDIIIM      ?             
                                             M?IIIIIIIIII.      M8MMIIIIIIIII.        M            
                                             MINIIIIIIII       ,    NIIIIIII$     R    N           
                                          .MI?N8IIIIIIIN      &7    7IIIIIIM      M7  M           
                                         .IIIIIIIMIIIII=      &&     DIIIIIIIIM        D           
                                         MIIIIIIIIIIIIIM             ?IIIIIIIIIIM     M            
                                         ?IIIDIIIIIIIIIIN           MIIIIIIIIIIIIIN M.             
                                         IIIIIOIIIIIIIIIIM        ,IIIIIIIIIIIIIIIII$              
                                         7IIIIIMIIIIIIIIIII?NMMM8IMIIIIIIIIIIIIIIIIIIM             
                                         MIIIIIIIIIIIIIIIIMMMMM7IIIIIIIIIIIIIIIIIIIIIID            
                                         .IIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIM            
                                          NIIIIIIIIIIIIIIMIIIIIIIIIIIIIIIIIIIIMM?IIMM             
                                           NIIIIIIIIIIII7IIIIIIIIIMIIIIIIIIIIIIIIIIIIID.           
                                             IMMNIIIIIIIIIIIIIIII7IIIIMIIIMIIIIIII?II?IIIIIII8.    
                                                IIIIIIIIIIIIIIIIIIIIIIIIIIIIIIOIII?IIIIIIIIIII    
                                                IIIIIIIIINCLETUSD7IIIIIIIIIIIIIIIIIIIIIIIIIIIIM    
                                                IIIIIIMMMMMMM      O   IMM7IIIIIIIIIIIIIIIIID      
                                                IIIIMMMMMMMMMMM::MIM     N   .OMMZIIIIIDN,         
                                               :IIIMMMMMMMMMMMMIIIIM.,      M     ..             
                                               NIIINZDOZZMMMMMDIII~             MN~               
                                               IIIIMZZZZZZMMMIIIM                                 
                                              DIIIIIIMMMMZIIIIIIIIM                                
                                              IIIIIIIIIIIIIIIIIIIII,                               
                                             OIIIIIIIIIIIIIIIIIIIIN                                
                                             IIIIIIIIIIIIIIIIID..                                  
                                            MIIIIIIIIIIIIIIII,                                     
                                          ,IIIIIIIIIIIIIIIII?                                      
                                        DIIMIIIIIIIIIIIIIIIN                                       
                                    DOZZ7IIMIIIIIIIIIIIIIIO                                        
                                :M7MZZZLOLI7IIIIIIIIIIIIII~                                        
                             OYIIIIIZZZZMIIIIZIIIIIIIIIIIMN                                        
                         ,MIIIIIIIIIMZZZZMIIIIIMIIIIIIIIIIIM                                       
                       MIIIIIIIIIIIIIZZZZMMIIIIII7MMNMMIIIIZM                                      
                    MIIIIIIIIIIIIIIIINZZZOIIMIIIIIIIIIIIII7ZZIO                                    
                 .MIIIIIIIIIIIIIIIIIIMZZZZIIIINOIIIIIIIIIMZZZIIIM                                  
                   
        """
        print(cletus_ascii)
