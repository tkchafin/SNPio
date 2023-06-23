import os
import sys
import warnings
import gzip
import re
import random
import requests

from typing import Optional, Union, List, Dict, Any, Tuple

# Make sure python version is >= 3.8
if sys.version_info < (3, 8):
    raise ImportError("Python < 3.8 is not supported!")

import numpy as np
import pandas as pd
import toytree as tt
from toytree.TreeParser import TreeParser

"""
NOTE:  Monkey patching a method in toytree because
There is a bug in the method that makes it incompatible
with Python 3.11. It tries to open a file with 'rU', which
is deprecated in Python 3.11.
"""
###############################################################
# Monkey patching begin
###############################################################
original_get_data_from_intree = TreeParser.get_data_from_intree


def patched_get_data_from_intree(self):
    """
    Load data from a file or string and return as a list of strings.
    The data contents could be one newick string; a multiline NEXUS format
    for one tree; multiple newick strings on multiple lines; or multiple
    newick strings in a multiline NEXUS format. In any case, we will read
    in the data as a list on lines.

    NOTE: This method is monkey patched from the toytree package (v2.0.5) because there is a bug that appears in Python 11 where it tries to open a file using 'rU'. 'rU' is is deprecated in Python 11, so I changed it to just ``with open(self.intree, 'r')``\. This has been fixed on the GitHub version of toytree, but it is not at present fixed in the pip or conda versions.
    """

    # load string: filename or data stream
    if isinstance(self.intree, (str, bytes)):
        # strip it
        self.intree = self.intree.strip()

        # is a URL: make a list by splitting a string
        if any([i in self.intree for i in ("http://", "https://")]):
            response = requests.get(self.intree)
            response.raise_for_status()
            self.data = response.text.strip().split("\n")

        # is a file: read by lines to a list
        elif os.path.exists(self.intree):
            with open(self.intree, "r") as indata:
                self.data = indata.readlines()

        # is a string: make into a list by splitting
        else:
            self.data = self.intree.split("\n")

    # load iterable: iterable of newick strings
    elif isinstance(self.intree, (list, set, tuple)):
        self.data = list(self.intree)


TreeParser.get_data_from_intree = patched_get_data_from_intree
##########################################################################
# Done monkey patching.
##########################################################################

from Bio.Align import MultipleSeqAlignment
from Bio.SeqRecord import SeqRecord
from Bio.Seq import Seq
import allel

try:
    from .popmap_file import ReadPopmap
    from ..utils.plotting import Plotting
    from ..plotting.plotting import Plotting as Plotting2
    from ..utils import sequence_tools
    from ..utils.misc import timer
    from ..utils.misc import class_performance_decorator
except (ModuleNotFoundError, ValueError):
    from read_input.popmap_file import ReadPopmap
    from utils.plotting import Plotting
    from plotting.plotting import Plotting as Plotting2

    from utils import sequence_tools
    from utils.misc import timer
    from utils.misc import class_performance_decorator


# Global resource data dictionary
resource_data = {}


@class_performance_decorator(measure=True)
class GenotypeData:
    """A class for handling and analyzing genotype data.

    The GenotypeData class provides methods to read, manipulate, and analyze genotype data in various formats, including VCF, Structure, and other custom formats. It allows for data preprocessing, allele encoding, and various data transformations.

    Notes:
        GenotypeData handles the following characters as missing data:
            - 'N'
            - '-'
            - '?'
            - '.'

        Thus, it treats gaps as missing data. 
        
        Some of the GenotypeData methods also force each site to be biallelic.

        Please keep this in mind when using GenotypeData.


    Args:
        filename (str or None): Path to input file containing genotypes. Defaults to None.

        filetype (str or None): Type of input genotype file. Possible values include: 'phylip', 'structure', 'vcf', or '012'. Defaults to None.

        popmapfile (str or None): Path to population map file. If supplied and filetype is one of the STRUCTURE formats, then the structure file is assumed to have NO popID column. Defaults to None.

        force_popmap (bool): If True, then samples not present in the popmap file will be excluded from the alignment. If False, then an error is raised if samples are present in the popmap file that are not present in the alignment. Defaults to False.

        exclude_pops (List[str] or None): List of population IDs to exclude from the alignment. Defaults to None.

        include_pops (List[str] or None): List of population IDs to include in the alignment. Populations not present in the include_pops list will be excluded. Defaults to None.

        guidetree (str or None): Path to input treefile. Defaults to None.
        qmatrix_iqtree (str or None): Path to iqtree output file containing Q rate matrix. Defaults to None.

        qmatrix (str or None): Path to file containing only Q rate matrix, and not the full iqtree file. Defaults to None.

        siterates (str or None): Path to file containing per-site rates, with 1 rate per line corresponding to 1 site. Not required if genotype_data is defined with the siterates or siterates_iqtree option. Defaults to None.

        siterates_iqtree (str or None): Path to \*.rates file output from IQ-TREE, containing a per-site rate table. Cannot be used in conjunction with siterates argument. Not required if the siterates or siterates_iqtree options were used with the GenotypeData object. Defaults to None.

        plot_format (str): Format to save report plots. Valid options include: 'pdf', 'svg', 'png', and 'jpeg'. Defaults to 'pdf'.
        prefix (str): Prefix to use for output directory.

    Attributes:
        inputs (dict): GenotypeData keyword arguments as a dictionary.

        num_snps (int): Number of SNPs in the dataset.

        num_inds (int): Number of individuals in the dataset.

        populations (List[Union[str, int]]): Population IDs.

        popmap (dict): Dictionary object with SampleIDs as keys and popIDs as values.

        popmap_inverse (dict or None): Inverse dictionary of popmap, where popIDs are keys and lists of sampleIDs are values.

        samples (List[str]): Sample IDs in input order.

        snpsdict (dict or None): Dictionary with SampleIDs as keys and lists of genotypes as values.

        snp_data (List[List[str]]): Genotype data as a 2D list.

        genotypes_012 (List[List[int]], np.ndarray, or pd.DataFrame): Encoded 012 genotypes.

        genotypes_onehot (np.ndarray): One-hot encoded genotypes.

        genotypes_int (np.ndarray): Integer-encoded genotypes.

        alignment (Bio.MultipleSeqAlignment): Genotype data as a Biopython MultipleSeqAlignment object.

        vcf_attributes (dict): Attributes read in from VCF file.
        loci_indices (List[int]): Column indices for retained loci in filtered alignment.

        sample_indices (List[int]): Row indices for retained samples in the alignment.

        ref (List[str]): List of reference alleles of length num_snps.

        alt (List[str]): List of alternate alleles of length num_snps.

        q (QMatrix or None): Q-matrix object for phylogenetic tree.

        site_rates (SiteRates or None): Site rate data for phylogenetic tree.

        tree (NewickTree or None): Newick tree object.

    Methods:
        read_structure: Read data from a Structure file.

        read_vcf: Read data from a VCF file.

        read_phylip: Read data from a Phylip file.

        read_phylip: Read data from a Phylip file.

        read_012: Read data from a custom 012-encoded file format.

        read_tree: Read data from a newick file.

        q_from_iqtree: Read Q-matrix from \*.iqtree file.

        q_from_file: Read Q-matrix from file with only Q-matrix in it.

        siterates_from_iqtree: Read site rates from \*.rate file.

        siterates_from_file: Read site rates from file with only site rates in single column.

        write_structure: Write data to a Structure file.
        write_vcf: Write data to a VCF file.

        write_phylip: Write data to a Phylip file.
        read_popmap: Read in a popmap file.

        subset_vcf_data: Subset the data based on locus and sample indices.
        encode_012: Encode genotypes as 0,1,2 integers for reference, heterozygous, alternate alleles.

        decode_012: Decode 0,1,2 integers back to original genotypes.
        convert_onehot: Convert genotypes to one-hot encoding.
        convert_int_iupac: Convert genotypes to integer encoding (0-9) with IUPAC characters.

        missingness_reports: Create missingness reports from GenotypeData object.

    Example usage:
        Instantiate GenotypeData object

        genotype_data = GenotypeData(file="data.vcf", filetype="vcf", popmapfile="popmap.txt")

        # Access basic properties

        print(genotype_data.num_snps) # Number of SNPs in the dataset

        print(genotype_data.num_inds) # Number of individuals in the dataset

        print(genotype_data.populations) # Population IDs

        print(genotype_data.popmap) # Dictionary of SampleIDs as keys and popIDs as values
        print(genotype_data.samples) # Sample IDs in input order

        # Access transformed genotype data
        genotypes_012 = genotype_data.genotypes_012 # Encoded 012 genotypes as a 2D list

        genotypes_012_array = genotype_data.genotypes_012(fmt="numpy")

        genotypes_012_df = genotype_data.genotypes_012(fmt="pandas")

        genotypes_onehot = genotype_data.genotypes_onehot # One-hot encoded genotypes as a numpy array

        genotypes_int = genotype_data.genotypes_int # Integer-encoded genotypes (0-9) as a numpy array

        alignment = genotype_data.alignment # Genotype data as a Biopython MultipleSeqAlignment object

        # Access VCF file attributes

        vcf_attributes = genotype_data.vcf_attributes # Dictionary of VCF file attributes

        # Set and access additional properties

        genotype_data.q = q_matrix # Set q-matrix for phylogenetic tree

        q_matrix = genotype_data.q # Get q-matrix object
        genotype_data.site_rates = site_rates # Set site rate data for phylogenetic tree

        site_rates = genotype_data.site_rates # Get site rate data

        genotype_data.tree = newick_tree # Set newick tree data

        newick_tree = genotype_data.tree # Get newick tree object
    """

    resource_data = {}

    def __init__(
        self,
        filename: Optional[str] = None,
        filetype: Optional[str] = "auto",
        popmapfile: Optional[str] = None,
        force_popmap: bool = False,
        exclude_pops: Optional[List[str]] = None,
        include_pops: Optional[List[str]] = None,
        guidetree: Optional[str] = None,
        qmatrix_iqtree: Optional[str] = None,
        qmatrix: Optional[str] = None,
        siterates: Optional[str] = None,
        siterates_iqtree: Optional[str] = None,
        plot_format: Optional[str] = "pdf",
        prefix="imputer",
        verbose: bool = True,
        **kwargs,
    ) -> None:
        """
        Initialize the GenotypeData object."""

        self.filename = filename
        self.filetype = filetype.lower()
        self.popmapfile = popmapfile
        self.force_popmap = force_popmap
        self.exclude_pops = exclude_pops
        self.include_pops = include_pops
        self.guidetree = guidetree
        self.qmatrix_iqtree = qmatrix_iqtree
        self.qmatrix = qmatrix
        self.siterates = siterates
        self.siterates_iqtree = siterates_iqtree
        self.plot_format = plot_format
        self.prefix = prefix
        self.verbose = verbose
        self.measure = kwargs.get("measure", False)

        self._kwargs = {
            "filename": filename,
            "filetype": filetype,
            "popmapfile": popmapfile,
            "force_popmap": force_popmap,
            "exclude_pops": exclude_pops,
            "include_pops": include_pops,
            "guidetree": guidetree,
            "qmatrix_iqtree": qmatrix_iqtree,
            "qmatrix": qmatrix,
            "siterates": siterates,
            "siterates_iqtree": siterates_iqtree,
            "plot_format": plot_format,
            "prefix": prefix,
            "verbose": verbose,
        }

        if "vcf_attributes" in kwargs:
            self._vcf_attributes = kwargs["vcf_attributes"]
        else:
            self._vcf_attributes = {
                "samples": None,
                "pos": None,
                "chrom": None,
                "vcf_id": None,
                "ref": None,
                "alt": None,
                "qual": None,
                "filter": None,
                "fmt": None,
                "calldata": None,
                "vcf_header": None,
            }

        self._samples: List[str] = []
        self._populations: List[Union[str, int]] = []
        self._ref = []
        self._alt = []
        self._q = None
        self._site_rates = None
        self._tree = None
        self._popmap = None
        self._popmap_inverse = None

        if self.qmatrix is not None and self.qmatrix_iqtree is not None:
            raise TypeError(
                "qmatrix and qmatrix_iqtree cannot both be provided."
            )

        if self.siterates is not None and self.siterates_iqtree is not None:
            raise TypeError(
                "siterates and siterates_iqtree cannot both be defined"
            )

        try:
            self._loci_indices = kwargs["loci_indices"]
        except KeyError:
            self._loci_indices = None

        try:
            self._sample_indices = kwargs["sample_indices"]
        except KeyError:
            self._sample_indices = None

        if self.filetype == "auto":
            filetype = self._detect_file_format(filename)

            if not filetype:
                raise AssertionError(
                    "File type could not be automatically detected. Please check the file for formatting errors or specify the file format as either 'phylip', 'structure', 'vcf', or '012'."
                )

        self._parse_filetype(filetype, popmapfile)

        if self.popmapfile is not None:
            self.read_popmap(
                popmapfile,
                force=force_popmap,
                include_pops=include_pops,
                exclude_pops=exclude_pops,
            )

        if force_popmap:
            # Subset VCF attributes in case samples were not in popmap file.
            if self.filetype == "vcf":
                self._vcf_attributes = self.subset_vcf_data(
                    self.loci_indices,
                    self.sample_indices,
                    self._vcf_attributes,
                    self.num_snps,
                    self.num_inds,
                )

    def _detect_file_format(self, filename: str) -> str:
        try:
            with open(filename, "r") as fin:
                lines = fin.readlines()
        except UnicodeDecodeError:
            with gzip.open(filename, "rt") as fin:
                lines = fin.readlines()

        # Check for VCF format
        if (
            any(line.startswith("##fileformat=VCF") for line in lines)
            or any(line.startswith("#CHROM") for line in lines)
            or any(line.startswith("##FORMAT") for line in lines)
            or any(line.startswith("##INFO") for line in lines)
        ):
            return "vcf"

        # Check for PHYLIP format
        try:
            num_samples, num_loci = map(int, lines[0].split())
            if num_samples == len(lines[1:]) and num_loci == len(
                lines[1].split()[1:]
            ):
                return "phylip"
        except ValueError:
            pass

        # Check for STRUCTURE or encoded 012 format
        if all(line.split()[0].isalpha() for line in lines[1:]):
            # Check for STRUCTURE format
            if any(int(x) > 2 for line in lines[1:] for x in line.split()[2:]):
                return "structure"
            # Check for encoded 012 format
            elif (
                sum(x == "0" for line in lines[1:] for x in line.split()[2:])
                / sum(1 for line in lines[1:] for x in line.split()[2:])
                > 0.5
            ):
                return "012"
        return False

    def _parse_filetype(
        self, filetype: Optional[str] = None, popmapfile: Optional[str] = None
    ) -> None:
        """
        Check the filetype and call the appropriate function to read the file format.

        Args:
            filetype (Optional[str], default=None): Filetype. Supported values include: "phylip", "structure", "vcf", and "012".

            popmapfile (Optional[str], default=None): Path to population map file.

        Raises:
            OSError: If no filetype is specified.
            OSError: If an unsupported filetype is provided.
        """
        if filetype is None:
            raise OSError("No filetype specified.\n")
        else:
            if filetype.lower() == "phylip":
                self.filetype = filetype
                self.read_phylip()
            elif filetype.lower() == "structure":
                self.filetype = "structure"
                has_popids = True if popmapfile is None else False
                self.read_structure(popids=has_popids)
            elif filetype == "012":
                self.filetype = filetype
                self.read_012()
            elif filetype == "vcf":
                self.filetype = filetype
                self.read_vcf()
            elif filetype is None:
                raise TypeError(
                    "filetype argument must be provided, but got NoneType."
                )
            else:
                raise OSError(f"Unsupported filetype provided: {filetype}\n")

            if self._loci_indices is None:
                self._loci_indices = list(range(self.num_snps))
            if self._sample_indices is None:
                self._sample_indices = list(range(self.num_inds))

            self._kwargs["filetype"] = self.filetype
            self._kwargs["loci_indices"] = self._loci_indices
            self._kwargs["sample_indices"] = self._sample_indices

    def _check_filetype(self, filetype: str) -> None:
        """
        Validate that the filetype is correct.

        Args:
            filetype (str): Filetype to use.

        Raises:
            TypeError: If the provided filetype does not match the current filetype.
        """
        if self.filetype is None:
            self.filetype = filetype
        elif self.filetype == filetype:
            pass
        else:
            raise TypeError(
                "GenotypeData read_XX() call does not match filetype!\n"
            )

    def read_tree(self, treefile: str) -> tt.tree:
        """
        Read Newick-style phylogenetic tree into toytree object.

        The Newick-style tree file should follow the format type 0 (see toytree documentation).

        Args:
            treefile (str): Path to the Newick-style tree file.

        Returns:
            toytree.tree object: The input tree as a toytree object.

        Raises:
            FileNotFoundError: If the tree file is not found.
            AssertionError: If the tree file is not readable.
        """
        if not os.path.isfile(treefile):
            raise FileNotFoundError(f"File {treefile} not found!")

        assert os.access(treefile, os.R_OK), f"File {treefile} isn't readable"

        return tt.tree(treefile, tree_format=0)

    def q_from_file(self, fname: str, label: bool = True) -> pd.DataFrame:
        """
        Read Q matrix from a file.

        Args:
            fname (str): Path to the Q matrix input file.

            label (bool): True if the nucleotide label order is present, False otherwise.

        Returns:
            pandas.DataFrame: The Q-matrix as a pandas DataFrame object.

        Raises:
            FileNotFoundError: If the Q matrix file is not found.
        """
        q = self._blank_q_matrix()

        if not label:
            print(
                "Warning: Assuming the following nucleotide order: A, C, G, T"
            )

        if not os.path.isfile(fname):
            raise FileNotFoundError(f"File {fname} not found!")

        with open(fname, "r") as fin:
            header = True
            qlines = list()
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                if header:
                    if label:
                        order = line.split()
                        header = False
                    else:
                        order = ["A", "C", "G", "T"]
                    continue
                else:
                    qlines.append(line.split())
        fin.close()

        for l in qlines:
            for index in range(0, 4):
                q[l[0]][order[index]] = float(l[index + 1])
        qdf = pd.DataFrame(q)
        return qdf.T

    def q_from_iqtree(self, iqfile: str) -> pd.DataFrame:
        """
        Read Q matrix from an IQ-TREE (\*.iqtree) file.

        The IQ-TREE file contains the standard output of an IQ-TREE run and includes the Q-matrix.

        Args:
            iqfile (str): Path to the IQ-TREE file (\*.iqtree).

        Returns:
            pandas.DataFrame: The Q-matrix as a pandas DataFrame.

        Raises:
            FileNotFoundError: If the IQ-TREE file could not be found.
            IOError: If the IQ-TREE file could not be read.
        """

        q = self._blank_q_matrix()
        qlines = list()
        try:
            with open(iqfile, "r") as fin:
                foundLine = False
                matlinecount = 0
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    if "Rate matrix Q" in line:
                        foundLine = True
                        continue
                    if foundLine:
                        matlinecount += 1
                        if matlinecount > 4:
                            break
                        stuff = line.split()
                        qlines.append(stuff)
                    else:
                        continue
        except (IOError, FileNotFoundError):
            raise FileNotFoundError(f"Could not open IQ-TREE file {iqfile}")

        # Populate q matrix with values from the IQ-TREE file
        order = [l[0] for l in qlines]
        for l in qlines:
            for index in range(0, 4):
                q[l[0]][order[index]] = float(l[index + 1])

        qdf = pd.DataFrame(q)
        return qdf.T

    def _blank_q_matrix(
        self, default: float = 0.0
    ) -> Dict[str, Dict[str, float]]:
        """
        Create a blank Q-matrix dictionary initialized with default values.

        Args:
            default (float, optional): Default value to initialize the Q-matrix cells. Defaults to 0.0.

        Returns:
            Dict[str, Dict[str, float]]: Blank Q-matrix dictionary.

        """
        q: Dict[str, Dict[str, float]] = dict()
        for nuc1 in ["A", "C", "G", "T"]:
            q[nuc1] = dict()
            for nuc2 in ["A", "C", "G", "T"]:
                q[nuc1][nuc2] = default
        return q

    def siterates_from_iqtree(self, iqfile: str) -> pd.DataFrame:
        """
        Read site-specific substitution rates from \*.rates file.

        The \*.rates file is an optional output file generated by IQ-TREE and contains a table of site-specific rates and rate categories.

        Args:
            iqfile (str): Path to \*.rates input file.

        Returns:
            List[float]: List of site-specific substitution rates.

        Raises:
            FileNotFoundError: If the rates file could not be found.
            IOError: If the rates file could not be read from.
        """
        s = []
        try:
            with open(iqfile, "r") as fin:
                for line in fin:
                    line = line.strip()
                    if (
                        not line
                        or line.startswith("#")
                        or line.lower().startswith("site")
                    ):
                        continue
                    else:
                        stuff = line.split()
                        s.append(float(stuff[1]))

        except (IOError, FileNotFoundError):
            raise IOError(f"Could not open iqtree file {iqfile}")
        return s

    def _validate_rates(self) -> None:
        """
        Validate the number of site rates matches the number of SNPs.

        Raises:
            ValueError: If the number of site rates does not match the number of SNPs.
        """
        if len(self._site_rates) != self.num_snps:
            raise ValueError(
                "The number of site rates was not equal to the number of snps in the alignment."
            )

    def siterates_from_file(self, fname: str) -> List[float]:
        """
        Read site-specific substitution rates from a file.

        Args:
            fname (str): Path to the input file.

        Returns:
            List[float]: List of site-specific substitution rates.
        """
        s = list()
        with open(fname, "r") as fin:
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                else:
                    s.append(float(line.split()[0]))
        fin.close()
        return s

    def _validate_seq_lengths(self) -> None:
        """Validate that all sequences have the same length.

        Raises:
            ValueError: If not all sequences (rows) are the same length.
        """
        # Make sure all sequences are the same length.
        all_same = all(len(row) == self.num_snps for row in self._snp_data)

        if not all_same:
            bad_rows = [
                i
                for i, row in enumerate(self.num_snps)
                if len(row) != self.num_snps
            ]

            bad_sampleids = [self._samples[i] for i in bad_rows]
            raise ValueError(
                f"The following sequences in the alignment were of unequal lengths: {','.join(bad_sampleids)}"
            )

    def read_structure(self, popids: bool = True) -> None:
        """
        Read a structure file and automatically detect its format.

        Args:
            popids (bool, optional): True if population IDs are present as the 2nd column in the structure file, otherwise False. Defaults to True.

        Raises:
            ValueError: If sample names do not match for the two-row format.
            ValueError: If population IDs do not match for the two-row format.
            ValueError: If not all sequences (rows) are the same length.
        """
        if self.verbose:
            print(f"\nReading structure file {self.filename}...")

        # Detect the format of the structure file
        onerow = self.detect_format()

        snp_data = list()
        with open(self.filename, "r") as fin:
            if not onerow:
                firstline = None
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    if not firstline:
                        firstline = line.split()
                        continue
                    else:
                        secondline = line.split()
                        if firstline[0] != secondline[0]:
                            raise ValueError(
                                f"Two rows per individual was "
                                f"specified but sample names do not match: "
                                f"{firstline[0]} and {secondline[0]}\n"
                            )

                        ind = firstline[0]
                        pop = None
                        if popids:
                            if firstline[1] != secondline[1]:
                                raise ValueError(
                                    f"Two rows per individual was "
                                    f"specified but population IDs do not "
                                    f"match {firstline[1]} {secondline[1]}\n"
                                )
                            pop = firstline[1]
                            self._populations.append(pop)
                            firstline = firstline[2:]
                            secondline = secondline[2:]
                        else:
                            firstline = firstline[1:]
                            secondline = secondline[1:]
                        self._samples.append(ind)
                        genotypes = merge_alleles(firstline, secondline)
                        snp_data.append(genotypes)
                        firstline = None
            else:  # If onerow:
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    firstline = line.split()
                    ind = firstline[0]
                    pop = None
                    if popids:
                        pop = firstline[1]
                        self._populations.append(pop)
                        firstline = firstline[2:]
                    else:
                        firstline = firstline[1:]
                    self._samples.append(ind)
                    genotypes = merge_alleles(firstline, second=None)
                    snp_data.append(genotypes)
                    firstline = None

        self._snp_data = snp_data
        self._validate_seq_lengths()

        if self.verbose:
            print(f"STRUCTURE file successfully loaded!")
            print(
                f"\nFound {self.num_snps} SNPs and {self.num_inds} "
                f"individuals...\n"
            )

    def write_structure(
        self,
        output_file: str,
        genotype_data=None,
        snp_data: List[List[str]] = None,
        samples: List[str] = None,
        verbose: bool = False,
    ) -> None:
        """
        Write a structure file.

        Args:
            output_file (str): The output filename.

            genotype_data (GenotypeData, optional): GenotypeData instance. Uses snp_data from the provided GenotypeData object to write the file. genotype_data and snp_data cannot both be provided.

            snp_data (List[List[str]], optional): snp_data object obtained from a GenotypeData object. genotype_data and snp_data cannot both be provided.

            samples (List[str], optional): List of sample IDs.

            verbose (bool, optional): If True, status updates are printed.

        Raises:
            ValueError: If genotypes are not presented as a pair for each SNP.
            TypeError: If using snp_data, samples must also be provided.
        """
        if verbose:
            print(f"\nWriting structure file {output_file}...")

        if genotype_data is not None and snp_data is not None:
            raise TypeError(
                "genotype_data and snp_data cannot both be NoneType"
            )

        elif genotype_data is None and snp_data is None:
            snp_data = self.snp_data
            samples = self.samples
            snpsdict = self.snpsdict

        elif genotype_data is not None and snp_data is None:
            snp_data = genotype_data.snp_data
            samples = genotype_data.samples
            snpsdict = genotype_data.snpsdict

        elif genotype_data is None and snp_data is not None:
            if samples is None:
                raise TypeError(
                    "If using snp_data, samples must also be provided."
                )
            snpsdict = self._make_snpsdict(samples=samples, snp_data=snp_data)

        with open(output_file, "w") as fout:
            for sample in samples:
                genotypes = list(
                    map(self._iupac_to_genotype, snpsdict[sample])
                )

                genotypes = [
                    allele
                    for genotype in genotypes
                    for allele in genotype.split("/")
                ]

                # The genotypes must be presented as a pair for each SNP
                if len(genotypes) % 2 != 0:
                    raise ValueError(
                        f"Genotypes for sample {sample} are not presented as pairs."
                    )

                # Split the genotypes into two lines for each sample
                # Selects every other element of the list.
                firstline_genotypes = genotypes[::2]
                secondline_genotypes = genotypes[1::2]

                fout.write(
                    sample
                    + "\t"
                    + "\t".join(map(str, firstline_genotypes))
                    + "\n"
                )
                fout.write(
                    sample
                    + "\t"
                    + "\t".join(map(str, secondline_genotypes))
                    + "\n"
                )

        if verbose:
            print("Successfully wrote STRUCTURE file!")

    def detect_format(self) -> bool:
        """
        Detect the format of the structure file (onerow or tworow).

        Returns:
            bool: True if the file is in one-row format, False if it is in two-row format.
        """
        with open(self.filename, "r") as fin:
            first_line = fin.readline().split()
            second_line = fin.readline().split()

        # If the first two lines have the same sample name, then
        # it's a two-row format
        onerow = first_line[0] != second_line[0]
        return onerow

    def read_phylip(self) -> None:
        """
        Populates GenotypeData object by parsing a Phylip file.

        Raises:
            ValueError: If all sequences are not the same length as specified in the header line.

            ValueError: If the number of individuals differs from the header line.
        """
        if self.verbose:
            print(f"\nReading phylip file {self.filename}...")

        self._check_filetype("phylip")
        snp_data = list()
        with open(self.filename, "r") as fin:
            first = True
            for line in fin:
                line = line.strip()
                if not line:  # If blank line.
                    continue
                if first:
                    first = False
                    header = line.split()
                    continue
                cols = line.split()
                inds = cols[0]
                seqs = cols[1]
                snps = [snp for snp in seqs]  # Split each site.
                snp_data.append(snps)

                self._samples.append(inds)

        self._snp_data = snp_data
        self._validate_seq_lengths()

        if self.verbose:
            print(f"PHYLIP file successfully loaded!")
            print(
                f"\nFound {self.num_snps} SNPs and {self.num_inds} "
                f"individuals...\n"
            )

    def read_vcf(self) -> None:
        """
        Read a VCF file into a GenotypeData object.

        Raises:
            ValueError: If the number of individuals differs from the header line.
        """
        if self.verbose:
            print(f"\nReading VCF file {self.filename}...")

        self._check_filetype("vcf")
        (
            vcf_header,
            vcf_colnames,
            compressed,
        ) = self._read_vcf_header(self.filename)

        # Load the VCF file using scikit-allel
        callset = allel.read_vcf(
            self.filename,
            fields=["*", "variants/INFO/*"],
            numbers={"calldata/CATG": 4},
        )

        # df = pd.read_csv(self.filename, sep="\t", )

        # Extract the VCF data
        self._samples = callset["samples"]
        chrom = callset["variants/CHROM"]
        pos = callset["variants/POS"]
        vcf_id = callset["variants/ID"]
        ref = callset["variants/REF"]
        alt = callset["variants/ALT"]
        qual = callset["variants/QUAL"]
        vcf_filter = callset["variants/FILTER_PASS"]

        info_fields = [
            key
            for key in callset.keys()
            if key.startswith("variants/")
            and not key.endswith(
                (
                    "samples",
                    "CHROM",
                    "POS",
                    "ID",
                    "REF",
                    "ALT",
                    "QUAL",
                    "FILTER_PASS",
                    "is_snp",
                    "numalt",
                    "altlen",
                )
            )
        ]

        format_fields = [
            key for key in callset.keys() if key.startswith("calldata/")
        ]

        info = {}
        for field in info_fields:
            info[field.split("/")[1]] = callset[field]

        fmt = []
        for field in format_fields:
            fmt.append(field.split("/")[1])

        def concat_arr2strings(arr2d):
            return np.array(",".join([a for a in arr2d]), dtype="U32")

        calldata = {
            k: v.astype(str)
            for k, v in callset.items()
            if k.startswith("calldata/") and not k.endswith("/GT")
        }

        calldata = {
            k: np.apply_along_axis(
                concat_arr2strings, 0, np.transpose(v, (2, 0, 1))
            )
            if len(v.shape) == 3
            else v
            for k, v in calldata.items()
        }

        self._snp_data = self._load_gt_calldata(callset)
        self._loci_indices = list(range(self.num_snps))
        self._sample_indices = list(range(self.num_inds))

        self._vcf_attributes = {
            "chrom": chrom,
            "pos": pos,
            "vcf_id": vcf_id,
            "ref": ref,
            "alt": alt,
            "qual": qual,
            "filter": vcf_filter,
            "info": info,
            "fmt": fmt,
            "calldata": calldata,  # Everything except GT
            "vcf_header": vcf_header,
        }

        self._validate_seq_lengths()

        if self.verbose:
            print(f"VCF file successfully loaded!")
            print(
                f"\nFound {self.num_snps} SNPs and {self.num_inds} "
                f"individuals...\n"
            )

    def _read_vcf_header(self, filename):
        """
        Reads the header from a VCF file.

        Args:
            filename (str): The path to the VCF file.

        Returns:
            Tuple[str, str, bool]: The header of the VCF file, column names line, and a flag indicating if the file is compressed.
        """
        header = ""
        colnames = ""
        compressed = False
        try:
            with open(filename, "rt") as f:
                for line in f:
                    if line.startswith("#"):
                        header += line
                        if line.startswith("#CHROM"):
                            colnames = line
                    else:
                        break
        except UnicodeDecodeError:
            with gzip.open(filename, "rt") as f:
                for line in f:
                    if line.startswith("#"):
                        header += line
                        if line.startswith("#CHROM"):
                            colnames = line
                    else:
                        break
            compressed = True
        return header, colnames, compressed

    def _load_gt_calldata(self, callset) -> List[List[str]]:
        """
        Load calldata/GT (genotypes) from a scikit-allel object.

        Args:
            callset (Dict[str, Union[List[int], List[str], np.ndarray]]): Callset from scikit-allel `read_vcf()` function.

        Returns:
            List[List[str]]: 2D list of shape (n_samples, n_loci) with single IUPAC base characters (including IUPAC ambiguity codes) as values.
        """

        # Define a mapping from pairs of nucleotides to IUPAC codes
        iupac_tups = {
            ("A", "C"): "M",
            ("A", "G"): "R",
            ("A", "T"): "W",
            ("C", "A"): "M",
            ("C", "G"): "S",
            ("C", "T"): "Y",
            ("G", "A"): "R",
            ("G", "C"): "S",
            ("G", "T"): "K",
            ("T", "A"): "W",
            ("T", "C"): "Y",
            ("T", "G"): "K",
            ("A", "A"): "A",
            ("T", "T"): "T",
            ("G", "G"): "G",
            ("C", "C"): "C",
            ("N", "N"): "N",
            ("A", "N"): "A",
            ("C", "N"): "C",
            ("T", "N"): "T",
            ("G", "N"): "G",
            ("N", "A"): "A",
            ("N", "C"): "C",
            ("N", "T"): "T",
            ("N", "G"): "G",
        }

        # Convert genotypes to IUPAC codes
        gt = allel.GenotypeArray(callset["calldata/GT"])

        # Identify missing calls
        is_missing = gt.is_missing()

        # Get the reference and alternate alleles
        ref = callset["variants/REF"]
        alt = callset["variants/ALT"]

        # Initialize arrays to hold the IUPAC codes for each allele
        iupac_array1 = np.empty(gt.shape[:-1], dtype="U1")
        iupac_array2 = np.empty(gt.shape[:-1], dtype="U1")

        # Expand dimensions of ref and alt to match the shape of the boolean mask
        ref_expanded = np.repeat(ref[:, np.newaxis], gt.shape[1], axis=1)
        alt_expanded = np.repeat(alt[:, :, np.newaxis], gt.shape[1], axis=2)

        # Fill in the IUPAC codes for homozygous reference calls
        iupac_array1[gt[:, :, 0] == 0] = ref_expanded[gt[:, :, 0] == 0]
        iupac_array2[gt[:, :, 1] == 0] = ref_expanded[gt[:, :, 1] == 0]

        # Fill in the IUPAC codes for homozygous alternate calls
        for i in range(1, alt.shape[1] + 1):
            iupac_array1[gt[:, :, 0] == i] = alt_expanded[:, i - 1][
                gt[:, :, 0] == i
            ]
            iupac_array2[gt[:, :, 1] == i] = alt_expanded[:, i - 1][
                gt[:, :, 1] == i
            ]

        # Replace missing values with 'N'
        iupac_array1[is_missing] = "N"
        iupac_array2[is_missing] = "N"

        # Combine the two alleles into tuples
        iupac_tuples = list(
            zip(iupac_array1.flatten(), iupac_array2.flatten())
        )

        # Map to IUPAC codes
        iupac_array = np.array(
            [iupac_tups[tuple(row)] for row in iupac_tuples]
        )

        # If you need to reshape the result back to the original shape:
        iupac_array = iupac_array.reshape(gt.shape[:-1])
        iupac_array = iupac_array.T

        return iupac_array.tolist()

    def _snpdata2gtarray(self, snpdata):
        """
        Converts a 2D list of IUPAC bases to a scikit-allel GenotypeArray.

        Args:
            snpdata (List[List[str]]): 2D list of shape (n_samples, n_loci) with single IUPAC base characters (including IUPAC ambiguity codes) as values.

        Returns:
            allel.GenotypeArray: GenotypeArray object of shape (n_loci, n_samples, 2).
        """

        # Define a mapping from IUPAC codes to pairs of nucleotides
        iupac_codes = {
            "M": ("A", "C"),
            "R": ("A", "G"),
            "W": ("A", "T"),
            "M": ("C", "A"),
            "S": ("C", "G"),
            "Y": ("C", "T"),
            "R": ("G", "A"),
            "S": ("G", "C"),
            "K": ("G", "T"),
            "W": ("T", "A"),
            "Y": ("T", "C"),
            "K": ("T", "G"),
            "A": ("A", "A"),
            "T": ("T", "T"),
            "G": ("G", "G"),
            "C": ("C", "C"),
            "N": ("N", "N"),
        }

        # Convert the 2D list to a numpy array
        snpdata_array = np.array(snpdata)
        snpdata_array = snpdata_array.T

        # Map the IUPAC codes to pairs of nucleotides
        snpdata_tuples = np.array(
            [iupac_codes[code] for code in snpdata_array.flatten()]
        )

        # Reshape the array back to the original shape
        snpdata_tuples = snpdata_tuples.reshape(snpdata_array.shape + (2,))
        return snpdata_tuples

    def write_phylip(
        self,
        output_file: str,
        genotype_data=None,
        snp_data: List[List[str]] = None,
        samples: List[str] = None,
        verbose: bool = False,
    ):
        """
        Write the alignment as a PHYLIP file.

        Args:
            output_file (str): Name of the output phylip file.

            genotype_data (GenotypeData, optional): GenotypeData instance. Uses snp_data from the provided GenotypeData object to write the file. genotype_data and snp_data cannot both be provided.

            snp_data (List[List[str]], optional): snp_data object obtained from a GenotypeData object. genotype_data and snp_data cannot both be provided. If snp_data is not None, then samples must also be provided.

            samples (List[str], optional): List of sample IDs. Must be provided if snp_data is not None.

            verbose (bool, optional): If True, status updates are printed.

        Raises:
            TypeError: If genotype_data and snp_data are both provided.
            TypeError: If samples is not provided when snp_data is provided.
            ValueError: If samples and snp_data are not the same length.
        """
        if verbose:
            print(f"\nWriting to PHYLIP file {output_file}...")

        if genotype_data is not None and snp_data is not None:
            raise TypeError(
                "genotype_data and snp_data cannot both be NoneType"
            )
        elif genotype_data is None and snp_data is None:
            snp_data = self.snp_data
            samples = self.samples
        elif genotype_data is not None and snp_data is None:
            snp_data = genotype_data.snp_data
            samples = genotype_data.samples
        elif genotype_data is None and snp_data is not None:
            if samples is None:
                raise TypeError("samples must be provided if snp_data is None")

        if len(samples) != len(snp_data):
            raise ValueError("samples and snp_data are not the same length.")

        with open(output_file, "w") as f:
            aln = pd.DataFrame(snp_data)
            n_samples, n_loci = aln.shape
            f.write(f"{n_samples} {n_loci}\n")
            for sample, sample_data in zip(samples, snp_data):
                genotype_data = "".join(str(x) for x in sample_data)
                f.write(f"{sample}\t{genotype_data}\n")

        if verbose:
            print(f"Successfully wrote PHYLIP file!")

    def write_vcf(
        self,
        output_filename: str,
        genotype_data=None,
        vcf_attributes=None,
        snp_data=None,
        verbose: bool = False,
    ) -> None:
        """
        Writes the GenotypeData object to a VCF file.

        Args:
            output_filename (str): The name of the VCF file to write to.

            genotype_data (Optional[GenotypeData], optional): A GenotypeData object.

            vcf_attributes (Optional[Dict[str, Union[np.ndarray, Dict[str, np.ndarray]]]]): vcf_attributes property from a GenotypeData object.

            snp_data (Optional[List[List[str]]]): snp_data property from a GenotypeData object. Only required if genotype_data is None.

            verbose (bool, optional): If True, print progress messages. Defaults to False.

        Raises:
            TypeError: If both genotype_data and vcf_attributes are provided.
            TypeError: If both genotype_data and snp_data are provided.
            TypeError: If vcf_attributes is provided without snp_data.
            TypeError: If snp_data is provided without samples.
            ValueError: If the shape of snp_data does not match the shape of vcf_attributes.
        """
        if verbose:
            print(f"\nWriting to VCF file {output_filename}...")

        if vcf_attributes is not None and genotype_data is not None:
            raise TypeError(
                "genotype_data and vcf_attributes cannot both be provided"
            )

        if genotype_data is not None and snp_data is not None:
            raise TypeError(
                "genotype_data and snp_data cannot both be provided"
            )

        if vcf_attributes is not None and snp_data is None:
            raise TypeError(
                "If vcf_attributes is provided, snp_data must also be provided. It can be accessed as a GenotypeData property."
            )

        if genotype_data is None and snp_data is None:
            snp_data = self.snp_data
            vcf_attributes = self.vcf_attributes

        if genotype_data is not None:
            snp_data = genotype_data.snp_data
            vcf_header = genotype_data.vcf_attributes["vcf_header"]
            chrom = genotype_data.vcf_attributes["chrom"]
            pos = genotype_data.vcf_attributes["pos"]
            vcf_id = genotype_data.vcf_attributes["id"]
            ref = genotype_data.vcf_attributes["ref"]
            alt = genotype_data.vcf_attributes["alt"]
            qual = genotype_data.vcf_attributes["qual"]
            fltr = genotype_data.vcf_attributes["filter"]
            info = genotype_data.vcf_attributes["info"]
            fmt = genotype_data.vcf_attributes["format"]
            calldata = genotype_data.vcf_attributes["calldata"]
        elif vcf_attributes is not None:
            vcf_header = vcf_attributes["vcf_header"]
            chrom = vcf_attributes["chrom"]
            pos = vcf_attributes["pos"]
            vcf_id = vcf_attributes["vcf_id"]
            ref = vcf_attributes["ref"]
            alt = vcf_attributes["alt"]
            qual = vcf_attributes["qual"]
            fltr = vcf_attributes["filter"]
            info = vcf_attributes["info"]
            fmt = vcf_attributes["fmt"]
            calldata = vcf_attributes["calldata"]

        gt = self._snpdata2gtarray(snp_data)

        # Convert the data to numpy arrays outside the loop
        snp_data = np.array(snp_data)
        alt = np.array(alt)
        calldata = {k: np.array(v) for k, v in calldata.items()}
        info = {k: np.array(v) for k, v in info.items()}

        # Transpose the data to loop over columns instead of rows
        snp_data = snp_data.T

        key = random.choice(list(calldata.keys()))

        if (
            snp_data.shape[0] != len(ref)
            or snp_data.shape[1] != calldata[key].shape[1]
        ):
            raise ValueError(
                f"snp_data shape != vcf_attributes shape: snp_data={snp_data.shape}, vcf_attributes={calldata[key].shape}. \n\nTry using the 'subset_vcf_attributes' function to subset the vcf_attributes."
            )

        alt = alt.T
        calldata = {k: v.T for k, v in calldata.items()}

        info_arrays = {
            key: np.char.add(f"{key}=", value.astype(str))
            for key, value in info.items()
        }

        info_arrays = np.array(list(info_arrays.values()))

        # Join the elements along the last axis
        info_result = np.apply_along_axis(
            lambda x: ";".join(x), 0, info_arrays
        )

        fltr = fltr.astype(str)
        fltr = np.where(fltr == "True", "PASS", "FAIL")

        # Preallocate a numpy array for the lines
        lines = np.empty((snp_data.shape[0],), dtype=object)

        # Loop over columns instead of rows
        for i in range(snp_data.shape[0]):
            gt_joined = np.char.add(gt[i, :, 0].astype(str), "/")
            gt_joined = np.char.add(gt_joined, gt[i, :, 1].astype(str))
            gt_joined = np.char.replace(gt_joined, "N/N", "./.")

            fmt_data = [
                calldata[f"calldata/{v}"][:, i]
                for v in fmt
                if v not in ["calldata/GT", "GT"]
            ]

            # Convert fmt_data into a 2D numpy array
            fmt_data = np.array(fmt_data)

            def concat_arr2strings(arr2d):
                return np.array(":".join([a for a in arr2d]), dtype="U32")

            # Join the elements along the first axis
            fmt_data = np.apply_along_axis(concat_arr2strings, 0, fmt_data)

            # Add a delimiter between gt_joined and fmt_data
            gt_joined = np.char.add(gt_joined, ":")
            # Now you can add fmt_data to gt_joined
            gt_joined = np.char.add(gt_joined, fmt_data)

            line = "\t".join(
                [
                    chrom[i],
                    pos[i].astype(str),
                    vcf_id[i],
                    ref[i],
                    ",".join(alt[alt[:, i].astype(bool), i]),
                    qual[i].astype(str),
                    fltr[i],
                    ":".join(fmt),
                    info_result[i].astype(str),
                    "\t".join(gt_joined),
                ]
            )

            # Write the line to the VCF file
            lines[i] = line + "\n"

        # Write the lines to the file
        with open(output_filename, "w") as f:
            f.write(vcf_header)
            f.writelines(lines)

        if verbose:
            print("Successfully wrote VCF file!")

    def read_012(self) -> None:
        """
        Read 012-encoded comma-delimited file.

        Raises:
            ValueError: Sequences differ in length.
        """
        if self.verbose:
            print(f"\nReading 012-encoded file {self.filename}...")

        self._check_filetype("012")
        snp_data = list()
        num_snps = list()

        with open(self.filename, "r") as fin:
            num_inds = 0
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                cols = line.split(",")
                inds = cols[0]
                snps = cols[1:]
                num_snps.append(len(snps))
                num_inds += 1
                snp_data.append(snps)
                self._samples.append(inds)

        if len(list(set(num_snps))) > 1:
            raise ValueError(
                "All sequences must be the same length; "
                "at least one sequence differs in length from the others\n"
            )

        df = pd.DataFrame(snp_data)
        df.replace("NA", "-9", inplace=True)
        df = df.astype("int")

        # Decodes 012 and converts to self._snp_data List[List[str]]
        self.genotypes_012 = df

        self._ref = None
        self._alt = None

        if self.verbose:
            print(f"012 file successfully loaded!")
            print(
                f"\nFound {self.num_snps} SNPs and {self.num_inds} "
                f"individuals...\n"
            )

    def convert_012(
        self,
        snps: List[List[str]],
        vcf: bool = False,
        impute_mode: bool = False,
    ) -> List[List[int]]:
        """
        Encode IUPAC nucleotides as 0 (reference), 1 (heterozygous), and 2 (alternate) alleles.

        Args:
            snps (List[List[str]]): 2D list of genotypes of shape (n_samples, n_sites).

            vcf (bool, optional): Whether or not VCF file input is provided. Not yet supported. Defaults to False.

            impute_mode (bool, optional): Whether or not convert_012() is called in impute mode. If True, then returns the 012-encoded genotypes and does not set the ``self.snp_data`` property. If False, it does the opposite. Defaults to False.

        Returns:
            List[List[int]], optional: 012-encoded genotypes as a 2D list of shape (n_samples, n_sites). Only returns value if ``impute_mode`` is True.

            List[int], optional: List of integers indicating bi-allelic site indexes.

            int, optional: Number of remaining valid sites.

        Warnings:
            UserWarning: If site is monomorphic.
            UserWarning: If site has >2 alleles.

        Todo:
            skip and impute_mode are now deprecated.
        """
        warnings.formatwarning = self._format_warning

        skip = 0
        snps_012 = []
        new_snps = []
        monomorphic_sites = []
        non_biallelic_sites = []
        all_missing = []

        if impute_mode:
            imp_snps = list()

        for i in range(0, len(snps)):
            new_snps.append([])

        # TODO: valid_sites is now deprecated.
        valid_sites = np.ones(len(snps[0]))
        for j in range(0, len(snps[0])):
            loc = []
            for i in range(0, len(snps)):
                if vcf:
                    loc.append(snps[i][j])
                else:
                    loc.append(snps[i][j].upper())

            if all(x == "N" for x in loc):
                all_missing.append(j)
                continue
            num_alleles = sequence_tools.count_alleles(loc, vcf=vcf)
            if num_alleles != 2:
                # If monomorphic
                if num_alleles < 2:
                    monomorphic_sites.append(j)
                    try:
                        ref = str(ref[0])
                    except IndexError:
                        ref = list(
                            map(
                                sequence_tools.get_major_allele,
                                loc,
                                [vcf for x in loc],
                            )
                        )
                    alt = None

                    if vcf:
                        for i in range(0, len(snps)):
                            gen = snps[i][j].split("/")
                            if gen[0] in ["-", "-9", "N"] or gen[1] in [
                                "-",
                                "-9",
                                "N",
                            ]:
                                new_snps[i].append(-9)

                            elif gen[0] == gen[1] and gen[0] == ref:
                                new_snps[i].append(0)

                            else:
                                new_snps[i].append(1)
                    else:
                        for i in range(0, len(snps)):
                            if loc[i] in ["-", "-9", "N"]:
                                new_snps[i].append(-9)

                            elif loc[i] == ref:
                                new_snps[i].append(0)

                            else:
                                new_snps[i].append(1)

                # If >2 alleles
                elif num_alleles > 2:
                    non_biallelic_sites.append(j)
                    all_alleles = sequence_tools.get_major_allele(loc, vcf=vcf)
                    all_alleles = [str(x[0]) for x in all_alleles]
                    ref = all_alleles.pop(0)
                    alt = all_alleles.pop(0)
                    others = all_alleles

                    if vcf:
                        for i in range(0, len(snps)):
                            gen = snps[i][j].split("/")
                            if gen[0] in ["-", "-9", "N"] or gen[1] in [
                                "-",
                                "-9",
                                "N",
                            ]:
                                new_snps[i].append(-9)

                            elif gen[0] == gen[1] and gen[0] == ref:
                                new_snps[i].append(0)

                            elif gen[0] == gen[1] and gen[0] == alt:
                                new_snps[i].append(2)

                            # Force biallelic
                            elif gen[0] == gen[1] and gen[0] in others:
                                new_snps[i].append(2)

                            else:
                                new_snps[i].append(1)
                    else:
                        for i in range(0, len(snps)):
                            if loc[i] in ["-", "-9", "N"]:
                                new_snps[i].append(-9)

                            elif loc[i] == ref:
                                new_snps[i].append(0)

                            elif loc[i] == alt:
                                new_snps[i].append(2)

                            # Force biallelic
                            elif loc[i] in others:
                                new_snps[i].append(2)

                            else:
                                new_snps[i].append(1)

            else:
                ref, alt = sequence_tools.get_major_allele(loc, vcf=vcf)
                ref = str(ref)
                alt = str(alt)

                if vcf:
                    for i in range(0, len(snps)):
                        gen = snps[i][j].split("/")
                        if gen[0] in ["-", "-9", "N"] or gen[1] in [
                            "-",
                            "-9",
                            "N",
                        ]:
                            new_snps[i].append(-9)

                        elif gen[0] == gen[1] and gen[0] == ref:
                            new_snps[i].append(0)

                        elif gen[0] == gen[1] and gen[0] == alt:
                            new_snps[i].append(2)

                        else:
                            new_snps[i].append(1)
                else:
                    for i in range(0, len(snps)):
                        if loc[i] in ["-", "-9", "N"]:
                            new_snps[i].append(-9)

                        elif loc[i] == ref:
                            new_snps[i].append(0)

                        elif loc[i] == alt:
                            new_snps[i].append(2)

                        else:
                            new_snps[i].append(1)

            # Set the ref and alt alleles for each column
            self._ref.append(ref)
            self._alt.append(alt)

        if monomorphic_sites:
            # TODO: Check here if column is all missing. What to do in this
            # case? Error out?
            warnings.warn(
                f"Monomorphic sites detected at the following locus indices: {','.join([str(x) for x in monomorphic_sites])}"
            )

        if non_biallelic_sites:
            warnings.warn(
                f" SNP column indices {','.join([str(x) for x in non_biallelic_sites])} had >2 alleles and was forced to "
                f"be bi-allelic. If that is not what you want, please "
                f"fix or remove the column and re-run.\n"
            )

        if all_missing:
            warnings.warn(
                f" SNP column indices {','.join([str(x) for x in all_missing])} had all missing data and were excluded from the alignment."
            )

            # Get elements in loci_indices that are not in all_missing
            self.loci_indices = list(set(self.loci_indices) - set(all_missing))
            self.loci_indices.sort()

        # TODO: skip and impute_mode are now deprecated.
        if skip > 0:
            if impute_mode:
                print(
                    f"\nWarning: Skipping {skip} non-biallelic sites following "
                    "imputation\n"
                )
            else:
                print(f"\nWarning: Skipping {skip} non-biallelic sites\n")

        for s in new_snps:
            if impute_mode:
                imp_snps.append(s)
            else:
                snps_012.append(s)

        if impute_mode:
            return (
                imp_snps,
                valid_sites,
                np.count_nonzero(~np.isnan(valid_sites)),
            )
        else:
            return snps_012

    def _make_snpsdict(
        self, samples: List[str] = None, snp_data: List[List[str]] = None
    ) -> Dict[str, List[str]]:
        """
        Make a dictionary with SampleIDs as keys and a list of SNPs associated with the sample as the values.

        Args:
            samples (List[str], optional): List of sample IDs. If not provided, uses self.samples.

            snp_data (List[List[str]], optional): 2D list of genotypes. If not provided, uses self.snp_data.

        Returns:
            Dict[str, List[str]]: Dictionary with sample IDs as keys and a list of SNPs as values.
        """
        if samples is None:
            samples = self.samples
        if snp_data is None:
            snp_data = self.snp_data

        snpsdict = {}
        for ind, seq in zip(samples, snp_data):
            snpsdict[ind] = seq
        return snpsdict

    def _format_warning(
        self, message, category, filename, lineno, file=None, line=None
    ) -> str:
        """
        Set the format of warnings.warn warnings.

        This method defines the format of warning messages printed by the warnings module when using `warnings.warn()`.

        Args:
            message (str): Warning message to be printed.

            category (str): Type of warning.

            filename (str): Name of the Python file where the warning was raised.

            lineno (str): Line number where the warning occurred.

        Returns:
            str: Formatted warning message.

        Note:
            To set the format of warnings, use `warnings.formatwarning = self._format_warning`.
        """
        return f"{filename}:{lineno}: {category.__name__}:{message}"

    def convert_onehot(
        self,
        snp_data: Union[np.ndarray, List[List[int]]],
        encodings_dict: Optional[Dict[str, int]] = None,
    ) -> np.ndarray:
        """
        Convert input data to one-hot encoded format.

        Args:
            snp_data (Union[np.ndarray, List[List[int]]]): Input 012-encoded data of shape (n_samples, n_SNPs).

            encodings_dict (Optional[Dict[str, int]]): Encodings to convert structure to phylip format. Defaults to None.

        Returns:
            np.ndarray: One-hot encoded data.

        Note:
            If the data file type is "phylip" and `encodings_dict` is not provided, default encodings for nucleotides are used.

            If the data file type is "structure1row" or "structure2row" and `encodings_dict` is not provided, default encodings for alleles are used.

            Otherwise, if `encodings_dict` is provided, it will be used for conversion.

        Warnings:
            If the data file type is "phylip" or "structure" and `encodings_dict` is not provided, a default encoding will be used. It is recommended to provide custom encodings for accurate conversion.
        """

        if self.filetype in ["vcf", "phylip"] and encodings_dict is None:
            onehot_dict = {
                "A": [1.0, 0.0, 0.0, 0.0],
                "T": [0.0, 1.0, 0.0, 0.0],
                "G": [0.0, 0.0, 1.0, 0.0],
                "C": [0.0, 0.0, 0.0, 1.0],
                "N": [0.0, 0.0, 0.0, 0.0],
                "W": [0.5, 0.5, 0.0, 0.0],
                "R": [0.5, 0.0, 0.5, 0.0],
                "M": [0.5, 0.0, 0.0, 0.5],
                "K": [0.0, 0.5, 0.5, 0.0],
                "Y": [0.0, 0.5, 0.0, 0.5],
                "S": [0.0, 0.0, 0.5, 0.5],
                "-": [0.0, 0.0, 0.0, 0.0],
            }

        elif self.filetype == "structure" and encodings_dict is None:
            onehot_dict = {
                "1/1": [1.0, 0.0, 0.0, 0.0],
                "2/2": [0.0, 1.0, 0.0, 0.0],
                "3/3": [0.0, 0.0, 1.0, 0.0],
                "4/4": [0.0, 0.0, 0.0, 1.0],
                "-9/-9": [0.0, 0.0, 0.0, 0.0],
                "1/2": [0.5, 0.5, 0.0, 0.0],
                "2/1": [0.5, 0.5, 0.0, 0.0],
                "1/3": [0.5, 0.0, 0.5, 0.0],
                "3/1": [0.5, 0.0, 0.5, 0.0],
                "1/4": [0.5, 0.0, 0.0, 0.5],
                "4/1": [0.5, 0.0, 0.0, 0.5],
                "2/3": [0.0, 0.5, 0.5, 0.0],
                "3/2": [0.0, 0.5, 0.5, 0.0],
                "2/4": [0.0, 0.5, 0.0, 0.5],
                "4/2": [0.0, 0.5, 0.0, 0.5],
                "3/4": [0.0, 0.0, 0.5, 0.5],
                "4/3": [0.0, 0.0, 0.5, 0.5],
            }

        else:
            if isinstance(snp_data, np.ndarray):
                snp_data = snp_data.tolist()

            onehot_dict = encodings_dict

        onehot_outer_list = list()

        n_rows = (
            len(self._samples) if encodings_dict is None else len(snp_data)
        )

        for i in range(n_rows):
            onehot_list = list()
            for j in range(len(snp_data[0])):
                onehot_list.append(onehot_dict[snp_data[i][j]])
            onehot_outer_list.append(onehot_list)

        return np.array(onehot_outer_list)

    def convert_int_iupac(
        self,
        snp_data: Union[np.ndarray, List[List[int]]],
        encodings_dict: Optional[Dict[str, int]] = None,
    ) -> np.ndarray:
        """
        Convert input data to integer-encoded format (0-9) based on IUPAC codes.

        Args:
            snp_data (numpy.ndarray of shape (n_samples, n_SNPs) or List[List[int]]): Input 012-encoded data.
            encodings_dict (Dict[str, int] or None): Encodings to convert structure to phylip format.

        Returns:
            numpy.ndarray: Integer-encoded data.

        Note:
            If the data file type is "phylip" or "vcf" and `encodings_dict` is not provided, default encodings based on IUPAC codes are used.

            If the data file type is "structure" and `encodings_dict` is not provided, default encodings for alleles are used.

            Otherwise, if `encodings_dict` is provided, it will be used for conversion.
        """

        if (self.filetype in ["phylip", "vcf"]) and encodings_dict is None:
            onehot_dict = {
                "A": 0,
                "T": 1,
                "G": 2,
                "C": 3,
                "W": 4,
                "R": 5,
                "M": 6,
                "K": 7,
                "Y": 8,
                "S": 9,
                "-": -9,
                "N": -9,
            }

        elif self.filetype == "structure" and encodings_dict is None:
            onehot_dict = {
                "1/1": 0,
                "2/2": 1,
                "3/3": 2,
                "4/4": 3,
                "1/2": 4,
                "2/1": 4,
                "1/3": 5,
                "3/1": 5,
                "1/4": 6,
                "4/1": 6,
                "2/3": 7,
                "3/2": 7,
                "2/4": 8,
                "4/2": 8,
                "3/4": 9,
                "4/3": 9,
                "-9/-9": -9,
            }

        else:
            if isinstance(snp_data, np.ndarray):
                snp_data = snp_data.tolist()

            onehot_dict = encodings_dict

        onehot_outer_list = list()

        n_rows = (
            len(self._samples) if encodings_dict is None else len(snp_data)
        )

        for i in range(n_rows):
            onehot_list = list()
            for j in range(len(snp_data[0])):
                onehot_list.append(onehot_dict[snp_data[i][j]])
            onehot_outer_list.append(onehot_list)

        return np.array(onehot_outer_list)

    def read_popmap(
        self,
        popmapfile: Optional[str],
        force: bool,
        include_pops: Optional[List[str]] = None,
        exclude_pops: Optional[List[str]] = None,
    ) -> None:
        """
        Read population map from file and associate samples with populations.

        Args:
            popmapfile (str): Path to the population map file.
            force (bool): If True, return a subset dictionary without the keys that weren't found. If False, raise an error if not all samples are present in the population map file.

            include_pops (Optional[List[str]]): List of populations to include. If provided, only samples belonging to these populations will be included in the popmap and alignment.

            exclude_pops (Optional[List[str]]): List of populations to exclude. If provided, samples belonging to these populations will be excluded from the popmap and alignment.

        Raises:
            ValueError: No samples were found in the GenotypeData object.

            ValueError: Samples are missing from the population map file.

            ValueError: The number of individuals in the population map file differs from the number of samples in the GenotypeData object.
        """
        self.popmapfile = popmapfile
        # Join popmap file with main object.
        if len(self._samples) < 1:
            raise ValueError("No samples in GenotypeData\n")

        # Instantiate popmap object
        my_popmap = ReadPopmap(popmapfile)
        popmap_ok = my_popmap.validate_popmap(self._samples, force=force)
        my_popmap.subset_popmap(include_pops, exclude_pops)
        self._sample_indices = my_popmap.sample_indices

        if not force and not popmap_ok:
            raise ValueError(
                f"Not all samples are present in supplied popmap "
                f"file: {my_popmap.filename}\n"
            )

        if not force and include_pops is None and exclude_pops is None:
            if len(my_popmap.popmap) != len(self._samples):
                raise ValueError(
                    f"The number of individuals in the popmap file "
                    f"({len(my_popmap)}) differs from the number of samples "
                    f"({len(self._samples)})\n"
                )

            for sample in self._samples:
                if sample in my_popmap:
                    self._populations.append(my_popmap.popmap[sample])
        else:
            new_samples_set = set(
                [x for x in self._samples if x in my_popmap.popmap]
            )
            if not new_samples_set:
                raise ValueError(
                    "No samples in the popmap file were found in the alignment file."
                )

            indices = [
                i for i, x in enumerate(self._samples) if x in new_samples_set
            ]

            self._samples = [self._samples[i] for i in indices]
            self._snp_data = [self._snp_data[i] for i in indices]
            self._populations = [
                my_popmap.popmap[x]
                for x in self._samples
                if x in my_popmap.popmap
            ]

        self._popmap = my_popmap.popmap
        self._popmap_inverse = my_popmap.popmap_flipped

    def decode_012(
        self,
        X,
        write_output=True,
        prefix="imputer",
        is_nuc=False,
    ):
        """
        Decode 012-encoded or 0-9 integer-encoded imputed data to STRUCTURE or PHYLIP format.

        Args:
            X (pandas.DataFrame, numpy.ndarray, or List[List[int]]): Imputed data to decode, encoded as 012 or 0-9 integers.

            write_output (bool, optional): If True, save the decoded output to a file. If False, return the decoded data as a DataFrame. Defaults to True.

            prefix (str, optional): Prefix to append to the output file name. Defaults to "output".

            is_nuc (bool, optional): Whether the encoding is based on nucleotides instead of 012. Defaults to False.

        Returns:
            str or pandas.DataFrame: If write_output is True, returns the filename where the imputed data was written. If write_output is False, returns the decoded data as a DataFrame.
        """
        if isinstance(X, pd.DataFrame):
            df = X.copy()
        elif isinstance(X, (np.ndarray, list)):
            df = pd.DataFrame(X)

        nuc = {
            "A/A": "A",
            "T/T": "T",
            "G/G": "G",
            "C/C": "C",
            "A/G": "R",
            "G/A": "R",
            "C/T": "Y",
            "T/C": "Y",
            "G/C": "S",
            "C/G": "S",
            "A/T": "W",
            "T/A": "W",
            "G/T": "K",
            "T/G": "K",
            "A/C": "M",
            "C/A": "M",
            "N/N": "N",
        }

        ft = self.filetype.lower()

        is_phylip = False
        if ft == "phylip" or ft == "vcf":
            is_phylip = True

        df_decoded = df.copy()

        # VAE uses [A,T,G,C] encodings. The other NN methods use [0,1,2] encodings.
        if is_nuc:
            classes_int = range(10)
            classes_string = [str(x) for x in classes_int]
            if is_phylip:
                gt = ["A", "T", "G", "C", "W", "R", "M", "K", "Y", "S", "N"]
            else:
                gt = [
                    "1/1",
                    "2/2",
                    "3/3",
                    "4/4",
                    "1/2",
                    "1/3",
                    "1/4",
                    "2/3",
                    "2/4",
                    "3/4",
                    "-9/-9",
                ]
            d = dict(zip(classes_int, gt))
            dstr = dict(zip(classes_string, gt))
            d.update(dstr)
            dreplace = {col: d for col in list(df.columns)}

        else:
            dreplace = dict()
            for col, ref, alt in zip(df.columns, self._ref, self._alt):
                # if site is monomorphic, set alt and ref state the same
                if alt is None:
                    alt = ref
                ref2 = f"{ref}/{ref}"
                alt2 = f"{alt}/{alt}"
                het2 = f"{ref}/{alt}"

                if is_phylip:
                    ref2 = nuc[ref2]
                    alt2 = nuc[alt2]
                    het2 = nuc[het2]

                d = {
                    "0": ref2,
                    0: ref2,
                    "1": het2,
                    1: het2,
                    "2": alt2,
                    2: alt2,
                }
                dreplace[col] = d

        df_decoded.replace(dreplace, inplace=True)

        if write_output:
            outfile = os.path.join(
                f"{self.prefix}_output", "alignments", "imputed"
            )

        if ft.startswith("structure"):
            of = f"{outfile}.str"
            if ft.startswith("structure2row"):
                for col in df_decoded.columns:
                    df_decoded[col] = (
                        df_decoded[col]
                        .str.split("/")
                        .apply(lambda x: list(map(int, x)))
                    )

                df_decoded.insert(0, "sampleID", self._samples)
                df_decoded.insert(1, "popID", self._populations)

                # Transform each element to a separate row.
                df_decoded = (
                    df_decoded.set_index(["sampleID", "popID"])
                    .apply(pd.Series.explode)
                    .reset_index()
                )

            elif ft.startswith("structure1row"):
                df_decoded = pd.concat(
                    [
                        df_decoded[c]
                        .astype(str)
                        .str.split("/", expand=True)
                        .add_prefix(f"{c}_")
                        for c in df_decoded.columns
                    ],
                    axis=1,
                )

            elif ft == "structure":
                for col in df_decoded.columns:
                    df_decoded[col] = (
                        df_decoded[col]
                        .str.split("/")
                        .apply(lambda x: list(map(int, x)))
                    )

                df_decoded.insert(0, "sampleID", self._samples)
                df_decoded.insert(1, "popID", self._populations)

                # Transform each element to a separate row.
                df_decoded = (
                    df_decoded.set_index(["sampleID", "popID"])
                    .apply(pd.Series.explode)
                    .reset_index()
                )

            if write_output:
                df_decoded.insert(0, "sampleID", self._samples)
                df_decoded.insert(1, "popID", self._populations)

                df_decoded.to_csv(
                    of,
                    sep="\t",
                    header=False,
                    index=False,
                )

        elif ft.startswith("phylip"):
            of = f"{outfile}.phy"
            header = f"{self.num_inds} {self.num_snps}\n"

            if write_output:
                with open(of, "w") as fout:
                    fout.write(header)

                lst_decoded = df_decoded.values.tolist()

                with open(of, "a") as fout:
                    for sample, row in zip(self._samples, lst_decoded):
                        seqs = "".join([str(x) for x in row])
                        fout.write(f"{sample}\t{seqs}\n")

        if write_output:
            return of
        else:
            return df_decoded.values.tolist()

    def missingness_reports(
        self,
        zoom=True,
        prefix=None,
        horizontal_space=0.6,
        vertical_space=0.6,
        bar_color="gray",
        heatmap_palette="magma",
        plot_format="pdf",
        dpi=300,
    ):
        """
        Generate missingness reports and plots.

        The function will write several comma-delimited report files:

            1) individual_missingness.csv: Missing proportions per individual.

            2) locus_missingness.csv: Missing proportions per locus.

            3) population_missingness.csv: Missing proportions per population (only generated if popmapfile was passed to GenotypeData).

            4) population_locus_missingness.csv: Table of per-population and per-locus missing data proportions.

        A file missingness.<plot_format> will also be saved. It contains the following subplots:

            1) Barplot with per-individual missing data proportions.

            2) Barplot with per-locus missing data proportions.

            3) Barplot with per-population missing data proportions (only if popmapfile was passed to GenotypeData).

            4) Heatmap showing per-population + per-locus missing data proportions (only if popmapfile was passed to GenotypeData).

            5) Stacked barplot showing missing data proportions per-individual.

            6) Stacked barplot showing missing data proportions per-population (only if popmapfile was passed to GenotypeData).

        If popmapfile was not passed to GenotypeData, then the subplots and report files that require populations are not included.

        Args:
            zoom (bool, optional): If True, zoom in to the missing proportion range on some of the plots. If False, the plot range is fixed at [0, 1]. Defaults to True.

            prefix (str, optional): Prefix for output directory and files. Plots and files will be written to a directory called <prefix>_reports. The report directory will be created if it does not already exist. Defaults to 'imputer'.

            horizontal_space (float, optional): Set the width spacing between subplots. If your plots are overlapping horizontally, increase horizontal_space. If your plots are too far apart, decrease it. Defaults to 0.6.

            vertical_space (float, optional): Set the height spacing between subplots. If your plots are overlapping vertically, increase vertical_space. If your plots are too far apart, decrease it. Defaults to 0.6.

            bar_color (str, optional): Color of the bars on the non-stacked bar plots. Can be any color supported by matplotlib. See the matplotlib.pyplot.colors documentation. Defaults to 'gray'.
            heatmap_palette (str, optional): Palette to use for the heatmap plot. Can be any palette supported by seaborn. See the seaborn documentation. Defaults to 'magma'.

            plot_format (str, optional): Format to save the plots. Can be any of the following: "pdf", "png", "svg", "ps", "eps". Defaults to "pdf".

            dpi (int): The resolution in dots per inch. Defaults to 300.
        """
        params = dict(
            zoom=zoom,
            prefix=prefix,
            horizontal_space=horizontal_space,
            vertical_space=vertical_space,
            bar_color=bar_color,
            heatmap_palette=heatmap_palette,
            plot_format=plot_format,
            dpi=dpi,
        )

        df = pd.DataFrame(self._snp_data)
        df.replace(-9, np.nan, inplace=True)

        report_path = os.path.join(f"{prefix}_output", "reports")
        os.makedirs(report_path, exist_ok=True)

        loc, ind, poploc, poptotal, indpop = Plotting.visualize_missingness(
            self, df, **params
        )

        self._report2file(ind, report_path, "individual_missingness.csv")
        self._report2file(loc, report_path, "locus_missingness.csv")

        if self._populations is not None:
            self._report2file(
                poploc, report_path, "per_pop_and_locus_missingness.csv"
            )
            self._report2file(
                poptotal, report_path, "population_missingness.csv"
            )
            self._report2file(
                indpop,
                report_path,
                "population_locus_missingness.csv",
                header=True,
            )

    def _report2file(
        self,
        df: pd.DataFrame,
        report_path: str,
        mypath: str,
        header: bool = False,
    ) -> None:
        """
        Write a DataFrame to a CSV file.

        Args:
            df (pandas.DataFrame): DataFrame to be written to the file.
            report_path (str): Path to the report directory.

            mypath (str): Name of the file to write.

            header (bool, optional): Whether to include the header row in the file. Defaults to False.
        """
        df.to_csv(
            os.path.join(report_path, mypath), header=header, index=False
        )

    def subset_vcf_data(
        self,
        loci_indices: List[int],
        sample_indices: List[int],
        vcf_attributes: Dict[str, Any],
        num_snps: int,
        num_inds: int,
    ) -> Dict[str, Union[Dict[str, np.ndarray], np.ndarray]]:
        """
        Subsets the data in the GenotypeData object based on the provided lists of locus and sample indices.

        Args:
            loci_indices (List[int]): Indices of loci to include.

            sample_indices (List[int]): Indices of samples to include.

            vcf_attributes (Dict[str, Any]): Dictionary of VCF attributes.

            num_snps (int): Total number of SNPs.

            num_inds (int): Total number of individuals.

        Returns:
            Dict[str, Union[Dict[str, np.ndarray], np.ndarray]]: Dictionary of subsetted VCF attributes.
        """

        subsetted_vcf_attributes = {}

        if loci_indices is None:
            loci_indices = list(range(num_snps))

        for key in vcf_attributes.keys():
            if (
                not key.startswith("calldata/")
                and not key == "vcf_header"
                and not key == "fmt"
            ):
                if not isinstance(vcf_attributes[key], dict):
                    subsetted_vcf_attributes[key] = np.array(
                        [vcf_attributes[key][i] for i in loci_indices]
                    )
                else:
                    subsetted_vcf_attributes[key] = {}
                    for k2 in vcf_attributes[key].keys():
                        subsetted_vcf_attributes[key][k2] = np.array(
                            [vcf_attributes[key][k2][i] for i in loci_indices]
                        )

        if sample_indices is None:
            sample_indices = list(range(num_inds))
        for k, v in vcf_attributes.items():
            if k == "calldata":
                for key in v.keys():
                    if isinstance(v, dict):
                        if len(v[key].shape) == 2:
                            res = {
                                k2: v2[loci_indices, :] for k2, v2 in v.items()
                            }
                            res = {
                                k2: v2[:, sample_indices]
                                for k2, v2 in res.items()
                            }
                        elif len(v[key].shape) == 1:
                            res = {
                                k2: v2[loci_indices] for k2, v2 in v.items()
                            }
                        else:
                            raise IndexError(
                                "Incorrectly shaped array in vcf_attributes"
                            )
                subsetted_vcf_attributes[k] = res

        subsetted_vcf_attributes["fmt"] = vcf_attributes["fmt"]
        subsetted_vcf_attributes["vcf_header"] = self._subset_vcf_header(
            vcf_attributes["vcf_header"], sample_indices
        )

        return subsetted_vcf_attributes

    def _subset_vcf_header(
        self, vcf_header: str, sample_indices: List[int]
    ) -> str:
        """
        Subset the VCF header based on the provided sample indices.

        Args:
            vcf_header (str): VCF header string.

            sample_indices (List[int]): Indices of samples to include.

        Returns:
            str: Subsetted VCF header.
        """
        header = re.split("\n|\t", vcf_header)
        chrom_idx = header.index("#CHROM")
        fmt_idx = header.index("FORMAT")
        sample_idx = fmt_idx + 1
        subset_samples = header[sample_idx:]
        subset_chrom = header[chrom_idx : fmt_idx + 1]
        subset_chrom[-1] = subset_chrom[-1] + "\t"
        desc = header[:chrom_idx]
        subset_samples = [subset_samples[i] for i in sample_indices]
        subset_samples = "\t".join(subset_samples)
        subset_chrom = "\t".join(subset_chrom)
        desc = "\n".join(desc)
        desc = desc.strip()
        new_header = desc + "\n" + subset_chrom + subset_samples
        return new_header

    def _genotype_to_iupac(self, genotype: str) -> str:
        """
        Convert a genotype string to its corresponding IUPAC code.

        Args:
            genotype (str): Genotype string in the format "x/y".

        Returns:
            str: Corresponding IUPAC code for the input genotype. Returns 'N' if the genotype is not in the lookup dictionary.
        """
        iupac_dict = {
            "0/0": "A",
            "1/1": "T",
            "2/2": "C",
            "3/3": "G",
            "0/1": "W",
            "0/2": "M",
            "0/3": "R",
            "1/2": "Y",
            "1/3": "K",
            "2/3": "S",
            "-9/-9": "N",
        }
        return iupac_dict.get(genotype, "N")

    def _iupac_to_genotype(self, iupac_code: str) -> str:
        """
        Convert an IUPAC code to its corresponding genotype string.

        Args:
            iupac_code (str): IUPAC code.

        Returns:
            str: Corresponding genotype string for the input IUPAC code. Returns '-9/-9' if the IUPAC code is not in the lookup dictionary.
        """
        genotype_dict = {
            "A": "0/0",
            "T": "1/1",
            "C": "2/2",
            "G": "3/3",
            "W": "0/1",
            "M": "0/2",
            "R": "0/3",
            "Y": "1/2",
            "K": "1/3",
            "S": "2/3",
            "N": "-9/-9",
        }
        return genotype_dict.get(iupac_code, "-9/-9")

    def calc_missing(
        self, df: pd.DataFrame, use_pops: bool = True
    ) -> Tuple[
        pd.Series,
        pd.Series,
        Optional[pd.DataFrame],
        Optional[pd.Series],
        Optional[pd.DataFrame],
    ]:
        """
        Calculate missing value statistics based on a DataFrame.

        Args:
            df (pd.DataFrame): Input DataFrame containing genotype data.

            use_pops (bool, optional): If True, calculate statistics per population. Defaults to True.

        Returns:
            Tuple[pd.Series, pd.Series, Optional[pd.DataFrame], Optional[pd.Series], Optional[pd.DataFrame]]: A tuple of missing value statistics:

            - loc (pd.Series): Missing value proportions per locus.

            - ind (pd.Series): Missing value proportions per individual.

            - poploc (Optional[pd.DataFrame]): Missing value proportions per population and locus. Only returned if use_pops=True.

            - poptot (Optional[pd.Series]): Missing value proportions per population. Only returned if use_pops=True.

            - indpop (Optional[pd.DataFrame]): Missing value proportions per individual and population. Only returned if use_pops=True.
        """
        # Get missing value counts per-locus.
        loc = df.isna().sum(axis=0) / self.num_inds
        loc = loc.round(2)

        # Get missing value counts per-individual.
        ind = df.isna().sum(axis=1) / self.num_snps
        ind = ind.round(2)

        poploc = None
        poptot = None
        indpop = None
        if use_pops:
            popdf = df.copy()
            popdf.index = self._populations
            misscnt = popdf.isna().groupby(level=0).sum()
            n = popdf.groupby(level=0).size()
            poploc = misscnt.div(n, axis=0).round(2).T
            poptot = misscnt.sum(axis=1) / self.num_snps
            poptot = poptot.div(n, axis=0).round(2)
            indpop = df.copy()

        return loc, ind, poploc, poptot, indpop

    class _DataFormat012:
        def __init__(self, instance, is_structure: bool = False):
            """
            Initialize the _DataFormat012 class.

            Args:
                instance: An instance of the GenotypeData class.

                is_structure (bool, optional): Specify whether the data is in STRUCTURE format. Defaults to False.
            """
            self.instance = instance
            self.is_structure = is_structure

        def __call__(self, fmt="list"):
            """
            Convert genotype data in 012 format to the specified output format.

            Args:
                fmt (str, optional): The desired output format. Supported formats: 'list', 'numpy', 'pandas'. Defaults to 'list'.

            Returns:
                The converted genotype data in the specified format.

            Raises:
                ValueError: Invalid format supplied.
            """
            if fmt == "list":
                return list(
                    self.instance.convert_012(
                        self.instance.snp_data, vcf=self.is_structure
                    )
                )

            elif fmt == "numpy":
                return np.array(
                    self.instance.convert_012(
                        self.instance.snp_data, vcf=self.is_structure
                    )
                )

            elif fmt == "pandas":
                return pd.DataFrame.from_records(
                    self.instance.convert_012(
                        self.instance.snp_data, vcf=self.is_structure
                    )
                )

            else:
                raise ValueError(
                    "Invalid format. Supported formats: 'list', 'numpy', 'pandas'"
                )

    @classmethod
    def plot_performance(cls, fontsize=14, color="#8C56E3", figsize=(16, 9)):
        """Plots the performance metrics: CPU Load, Memory Footprint, and Execution Time.

        Takes a dictionary of performance data and plots the metrics for each of the methods. The resulting plot is saved in a .png file in the ``tests`` directory.

        Args:
            resource_data (dict): Dictionary with performance data. Keys are method names, and values are dictionaries with keys 'cpu_load', 'memory_footprint', and 'execution_time'.

            fontsize (int, optional): Font size to be used in the plot. Defaults to 14.

            color (str, optional): Color to be used in the plot. Should be a valid color string. Defaults to "#8C56E3".

            figsize (tuple, optional): Size of the figure. Should be a tuple of two integers. Defaults to (16, 9).

        Returns:
            None. The function saves the plot as a .png file.
        """
        Plotting2.plot_performance(
            cls.resource_data, fontsize=fontsize, color=color, figsize=figsize
        )

    @property
    def inputs(self):
        """Get GenotypeData keyword arguments as a dictionary."""
        return self._kwargs

    @inputs.setter
    def inputs(self, value):
        """Setter method for class keyword arguments."""
        self._kwargs = value

    @property
    def num_snps(self) -> int:
        """Number of snps in the dataset.

        Returns:
            int: Number of SNPs per individual.
        """
        return len(self._snp_data[0])

    @property
    def num_inds(self) -> int:
        """Number of individuals in dataset.

        Returns:
            int: Number of individuals in input data.
        """
        return len(self._snp_data)

    @property
    def populations(self) -> List[Union[str, int]]:
        """Population Ids.

        Returns:
            List[Union[str, int]]: Population IDs.
        """
        return self._populations

    @property
    def popmap(self) -> Dict[str, str]:
        """Dictionary object with SampleIDs as keys and popIDs as values."""
        return self._popmap

    @popmap.setter
    def popmap(self, value):
        """Dictionary with SampleIDs as keys and popIDs as values."""
        if not isinstance(value, dict):
            raise TypeError(
                f"popmap must be a dictionary object, but got {type(value)}."
            )

        if not all(isinstance(v, (str, int)) for v in value.values()):
            raise TypeError(f"popmap values must be strings or integers")
        self._popmap = value

    @property
    def popmap_inverse(self) -> None:
        return self._popmap_inverse

    @popmap_inverse.setter
    def popmap_inverse(self, value) -> Dict[str, str]:
        if not isinstance(value, dict):
            raise TypeError(
                f"popmap_inverse must be a dictionary object, but got {type(value)}"
            )

        if all(isinstance(v, list) for v in value.values()):
            raise TypeError(
                f"popmap_inverse values must be lists of sampleIDs for the given populationID key"
            )

        self._popmap_inverse = value

    @property
    def samples(self) -> List[str]:
        """Sample IDs in input order.

        Returns:
            List[str]: Sample IDs in input order.
        """
        return self._samples

    @samples.setter
    def samples(self, value) -> None:
        self._samples = value

    @property
    def snpsdict(self) -> Dict[str, List[str]]:
        """
        Dictionary with Sample IDs as keys and lists of genotypes as values.
        """
        self._snpsdict = self._make_snpsdict()
        return self._snpsdict

    @snpsdict.setter
    def snpsdict(self, value):
        """Set snpsdict object, which is a dictionary with sample IDs as keys and lists of genotypes as values."""
        self._snpsdict = value

    @property
    def snp_data(self) -> List[List[str]]:
        return self._snp_data

    @snp_data.setter
    def snp_data(self, value) -> None:
        if not isinstance(value, list):
            if isinstance(value, np.ndarray):
                value = value.tolist()
            elif isinstance(value, pd.DataFrame):
                value = value.values.tolist()
            elif isinstance(value, MultipleSeqAlignment):
                value = [list(str(record.seq)) for record in value]
            else:
                raise TypeError(
                    f"snp_data must be a list, numpy array, pandas dataframe, or MultipleSeqAlignment, but got {type(value)}"
                )
        self._snp_data = value
        self._validate_seq_lengths()

    @property
    def genotypes_012(
        self,
    ) -> Union[List[List[int]], np.ndarray, pd.DataFrame]:
        """Encoded 012 genotypes as a 2D list, numpy array, or pandas DataFrame.

        The examples below show how to return the different format types.

        Returns:
            List[List[int]], np.ndarray, or pd.DataFrame: encoded 012 genotypes.

        Examples:
            >>># Get a 2D list.
            >>>gt_list = GenotypeData.genotypes_012
            >>>
            >>># Get a numpy array.
            >>>gt_array = GenotypeData.genotypes_012(fmt="numpy")
            >>>
            >>># Get a pandas DataFrame.
            >>>gt_df = GenotypeData.genotypes_012(fmt="pandas")
        """
        is_str = True if self.filetype.startswith("structure") else False
        return self._DataFormat012(self, is_structure=is_str)

    @genotypes_012.setter
    def genotypes_012(self, value) -> List[List[int]]:
        self._snp_data = self.decode_012(value, write_output=False)

    @property
    def genotypes_onehot(self) -> Union[np.ndarray, List[List[List[float]]]]:
        """One-hot encoded snps format.

        Returns:
            numpy.ndarray: One-hot encoded numpy array of shape (n_samples, n_sites).
        """
        return self.convert_onehot(self._snp_data)

    @property
    def genotypes_int(self) -> np.ndarray:
        """Integer-encoded (0-9 including IUPAC characters) snps format.

        Returns:
            numpy.ndarray: Array of shape (n_samples, n_sites), integer-encoded from 0-9 with IUPAC characters.
        """
        arr = self.convert_int_iupac(self._snp_data)
        return arr

    @property
    def alignment(self) -> List[MultipleSeqAlignment]:
        """Get alignment as a biopython MultipleSeqAlignment object.

        This is good for printing and visualizing the alignment. If you want the alignment as a List[List[str]] object, then use the ``snp_data`` property instead.
        """
        is_str = True if self.filetype.startswith("structure") else False

        if is_str:
            snp_data = [
                [self._genotype_to_iupac(g) for g in row]
                for row in self._snp_data
            ]
        else:
            snp_data = self._snp_data

        return MultipleSeqAlignment(
            [
                SeqRecord(Seq("".join(row)), id=sample)
                for sample, row in zip(self._samples, snp_data)
            ]
        )

    @alignment.setter
    def alignment(self, value) -> None:
        """
        Setter method for the alignment.

        Args:
            value (Bio.MultipleSeqAlignment, list, np.ndarray, pd.DataFrame): The MultipleSeqAlignment object to set as the alignment.

        Raises:
            TypeError: If the input value is not a MultipleSeqAlignment object, list, numpy array, or pandas DataFrame.
        """
        if isinstance(value, MultipleSeqAlignment):
            alignment_array = np.array(
                [list(str(record.seq)) for record in value]
            )
        elif isinstance(value, pd.DataFrame):
            # Convert list, numpy array, or pandas DataFrame to list
            alignment_array = value.values.tolist()
        elif isinstance(value, np.ndarray):
            alignment_array = value.tolist()
        elif isinstance(value, list):
            alignment_array = value
        else:
            raise TypeError(
                "alignment must be a MultipleSequenceAlignment object, list, numpy array, or pandas DataFrame."
            )

        self._snp_data = alignment_array

    @property
    def vcf_attributes(
        self,
    ) -> Dict[str, Union[Dict[str, np.ndarray], np.ndarray]]:
        """Attributes read in from VCF file.

        Returns:
            Dict[str, Union[Dict[str, np.ndarray], np.ndarray]]: Dictionary object with keys corresponding to VCF file attributes and values being either a dictionary of numpy arrays (if key == 'calldata') or numpy arrays (if key != 'calldata').
        """
        if all(v is None for v in self._vcf_attributes.values()):
            raise AttributeError(
                "vcf_attributes has not been defined. These attributes are only defined if the input file was in vcf format."
            )
        return self._vcf_attributes

    @vcf_attributes.setter
    def vcf_attributes(
        self, value: Dict[str, Union[Dict[str, np.ndarray], np.ndarray]]
    ) -> None:
        """Setter method for VCF file attributes dictionary."""
        self._vcf_attributes = value

    @property
    def loci_indices(self) -> List[int]:
        """Column indices for retained loci in filtered alignment."""
        return self._loci_indices

    @loci_indices.setter
    def loci_indices(self, value) -> None:
        """Column indices for retained loci in filtered alignment."""
        self._loci_indices = value

    @property
    def sample_indices(self) -> List[int]:
        """Row indices for retained samples in alignemnt."""
        return self._sample_indices

    @sample_indices.setter
    def sample_indices(self, value: List[int]) -> None:
        """Row indices for retained samples in alignemnt."""
        self._sample_indices = value
        self._samples = [x for i, x in enumerate(self._samples) if i in value]

    @property
    def ref(self) -> List[str]:
        """Get list of reference alleles of length num_snps."""
        return self._ref

    @ref.setter
    def ref(self, value: List[str]) -> None:
        """Setter for list of reference alleles of length num_snps."""
        self._ref = value

    @property
    def alt(self) -> List[str]:
        """Get list of alternate alleles of length num_snps."""
        return self._alt

    @alt.setter
    def alt(self, value) -> None:
        """Setter for list of alternate alleles of length num_snps."""
        self._alt = value

    @property
    def q(self):
        """Get q-matrix object for phylogenetic tree."""
        if self.qmatrix_iqtree is not None and self.qmatrix is None:
            self._q = self.q_from_iqtree(self.qmatrix_iqtree)
        elif self.qmatrix_iqtree is None and self.qmatrix is not None:
            self._q = self.q_from_file(self.qmatrix)
        elif (
            self.qmatrix is None
            and self.qmatrix_iqtree is None
            and self._q is None
        ):
            raise TypeError(
                "qmatrix or qmatrix_iqtree must be provided at class instantiation or the q property must be set to get the q object."
            )
        return self._q

    @q.setter
    def q(self, value):
        """Set q-matrix for phylogenetic tree."""
        self._q = value

    @property
    def site_rates(self):
        """Get site rate data for phylogenetic tree."""
        if self.siterates_iqtree is not None and self.siterates is None:
            self._site_rates = self.siterates_from_iqtree(
                self.siterates_iqtree
            )
            self._validate_rates()
        elif self.siterates_iqtree is None and self.siterates is not None:
            self._site_rates = self.siterates_from_file(self.siterates)
            self._validate_rates()
        elif (
            self.siterates_iqtree is None
            and self.siterates is None
            and self._site_rates is None
        ):
            raise TypeError(
                "siterates or siterates_iqtree must be provided at class instantiation or the site_rates property must be set to get the site_rates object."
            )
        self._site_rates = [
            self._site_rates[i]
            for i in range(len(self._site_rates))
            if i in self.loci_indices
        ]
        return self._site_rates

    @site_rates.setter
    def site_rates(self, value):
        """Set site_rates object."""
        self._site_rates = value

    @property
    def tree(self):
        """Get newick tree provided at class instantiation."""
        if self.guidetree is not None:
            self._tree = self.read_tree(self.guidetree)
        elif self.guidetree is None and self._tree is None:
            raise TypeError(
                "Either a guidetree file must be provided at class instantiation or the tree property must be set to get the tree object."
            )
        return self._tree

    @tree.setter
    def tree(self, value):
        """Setter for newick tree data."""
        self._tree = value


def merge_alleles(
    first: List[Union[str, int]],
    second: Optional[List[Union[str, int]]] = None,
) -> List[str]:
    """Merges first and second alleles in a structure file.

    Args:
        first (List[Union[str, int] or None): Alleles on the first line.

        second (List[Union[str, int]] or None, optional): Second row of alleles. Defaults to None.

    Returns:
        List[str]: VCF file-style genotypes (i.e., split by "/").

    Raises:
        ValueError: If the first and second lines have differing lengths.

        ValueError: If the line has a non-even number of alleles.
    """
    ret = list()
    if second is not None:
        if len(first) != len(second):
            raise ValueError(
                "First and second lines have different number of alleles\n"
            )
        else:
            for i in range(0, len(first)):
                ret.append(str(first[i]) + "/" + str(second[i]))
    else:
        if len(first) % 2 != 0:
            raise ValueError("Line has non-even number of alleles!\n")
        else:
            for i, j in zip(first[::2], first[1::2]):
                ret.append(str(i) + "/" + str(j))
    return ret
