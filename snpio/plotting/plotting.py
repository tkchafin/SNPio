import sys
import os
from pathlib import Path
from functools import reduce
import seaborn as sns
import matplotlib.colors as mpl_colors
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from sklearn.model_selection import train_test_split
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error
import math
import itertools

from typing import Tuple

import holoviews as hv
from holoviews import opts, dim
from holoviews.plotting.util import process_cmap
from holoviews import Overlay
from bokeh.plotting import show
from bokeh.plotting import save
from bokeh.resources import CDN
from bokeh.embed import file_html
import panel as pn

hv.extension("bokeh")

from ..utils import misc


class Plotting:
    def __init__(self, popgenio):
        self.alignment = popgenio.alignment
        self.popmap = popgenio.popmap
        self.populations = popgenio.populations

    @staticmethod
    def _plot_summary_statistics_per_sample(summary_stats, ax=None):
        """
        Plot summary statistics per sample.

        Args:
            ax (matplotlib.axes.Axes, optional): The axis on which to plot the summary statistics.
        """
        if ax is None:
            _, ax = plt.subplots()

        ax.plot(summary_stats["Ho"], label="Ho")
        ax.plot(summary_stats["He"], label="He")
        ax.plot(summary_stats["Pi"], label="Pi")
        ax.plot(summary_stats["Fst"], label="Fst")

        ax.set_xlabel("Locus")
        ax.set_ylabel("Value")
        ax.set_title("Summary Statistics per Sample")
        ax.legend()

    @staticmethod
    def _plot_summary_statistics_per_population(
        summary_stats, popmap, ax=None
    ):
        """
        Plot summary statistics per population.

        Args:
            ax (matplotlib.axes.Axes, optional): The axis on which to plot the summary statistics.
        """
        if ax is None:
            _, ax = plt.subplots()

        # Group the summary statistics by population.
        pop_summary_stats = summary_stats.groupby(
            popmap["PopulationID"]
        ).mean()

        ax.plot(pop_summary_stats["Ho"], label="Ho")
        ax.plot(pop_summary_stats["He"], label="He")
        ax.plot(pop_summary_stats["Pi"], label="Pi")
        ax.plot(pop_summary_stats["Fst"], label="Fst")

        ax.set_xlabel("Population")
        ax.set_ylabel("Value")
        ax.set_title("Summary Statistics per Population")
        ax.legend()

    @staticmethod
    def _plot_summary_statistics_per_population_grid(
        summary_statistics_df, show=False
    ):
        """
        Plot summary statistics per population using a Seaborn PairGrid plot.
        """
        g = sns.PairGrid(summary_statistics_df)
        g.map_upper(sns.scatterplot)
        g.map_lower(sns.kdeplot)
        g.map_diag(sns.kdeplot, lw=3, legend=False)

        g.savefig(
            "summary_statistics_per_population_grid.png", bbox_inches="tight"
        )

        if show:
            plt.show()

        plt.close()

    @staticmethod
    def _plot_summary_statistics_per_sample_grid(
        summary_statistics_df, show=False
    ):
        """
        Plot summary statistics per sample using a Seaborn PairGrid plot.
        """
        g = sns.PairGrid(summary_statistics_df)
        g.map_upper(sns.scatterplot)
        g.map_lower(sns.kdeplot)
        g.map_diag(sns.kdeplot, lw=3, legend=False)

        g.savefig(
            "summary_statistics_per_sample_grid.png", bbox_inches="tight"
        )

        if show:
            plt.show()

        plt.close()

    @classmethod
    def plot_summary_statistics(cls, summary_statistics_df, show=False):
        """
        Plot summary statistics per sample and per population on the same figure.
        """
        fig, axes = plt.subplots(1, 2, figsize=(15, 5), sharey=True)

        cls._plot_summary_statistics_per_sample(
            summary_statistics_df, ax=axes[0]
        )
        cls._plot_summary_statistics_per_population(
            summary_statistics_df, ax=axes[1]
        )

        plt.tight_layout()
        plt.savefig("summary_statistics.png")

        if show:
            plt.show()

        plt.close()

        cls._plot_summary_statistics_per_sample_grid(summary_statistics_df)
        cls._plot_summary_statistics_per_population_grid(summary_statistics_df)

    @staticmethod
    def plot_pca(pca, alignment, popmap, dimensions=2, show=False):
        """
        Plot the PCA scatter plot.

        Args:
            pca (sklearn.PCA): The fitted PCA object.
            dimensions (int): Number of dimensions to plot (2 or 3). Default is 2.
            save_file (str): Filename for the saved plot. Default is 'pca_plot.png'.
        """
        pca_transformed = pd.DataFrame(
            pca.transform(alignment),
            columns=[f"PC{i+1}" for i in range(pca.n_components_)],
        )

        popmap = pd.DataFrame(
            list(popmap.items()), columns=["SampleID", "PopulationID"]
        )

        popmap.columns = ["SampleID", "PopulationID"]

        pca_transformed["PopulationID"] = popmap["PopulationID"]

        if dimensions == 2:
            sns.scatterplot(
                data=pca_transformed, x="PC1", y="PC2", hue="PopulationID"
            )
        elif dimensions == 3:
            fig = plt.figure()
            ax = fig.add_subplot(111, projection="3d")
            sns.scatterplot(
                data=pca_transformed,
                x="PC1",
                y="PC2",
                z="PC3",
                hue="PopulationID",
                ax=ax,
            )
        else:
            raise ValueError("dimensions must be 2 or 3")

        plt.savefig("pca_plot.png")

        if show:
            plt.show()

    @staticmethod
    def plot_dapc(dapc, alignment, popmap, dimensions=2, show=False):
        """
        Plot the DAPC scatter plot.

        Args:
            dapc (sklearn.discriminant_analysis.LinearDiscriminantAnalysis): The fitted DAPC object.
            dimensions (int): Number of dimensions to plot (2 or 3). Default is 2.
            save_file (str): Filename for the saved plot. Default is 'dapc_plot.png'.
        """
        dapc_transformed = pd.DataFrame(
            dapc.transform(alignment),
            columns=[f"DA{i+1}" for i in range(dapc.n_components_)],
        )
        dapc_transformed["PopulationID"] = popmap["PopulationID"]

        if dimensions == 2:
            sns.scatterplot(
                data=dapc_transformed, x="DA1", y="DA2", hue="PopulationID"
            )
        elif dimensions == 3:
            fig = plt.figure()
            ax = fig.add_subplot(111, projection="3d")
            sns.scatterplot(
                data=dapc_transformed,
                x="DA1",
                y="DA2",
                z="DA3",
                hue="PopulationID",
                ax=ax,
            )
        else:
            raise ValueError("dimensions must be 2 or 3")

        plt.savefig("dapc_plot.png")

        if show:
            plt.show()

    @staticmethod
    def plot_dapc_cv(pca_transformed, popmap, n_components_range):
        """
        Plot the DAPC cross-validation results.

        Args:
            n_components_range (range): Range of principal components to perform cross-validation on.
        """
        rmse_scores = []

        for n in n_components_range:
            lda = LinearDiscriminantAnalysis(n_components=n)
            X_train, X_test, y_train, y_test = train_test_split(
                pca_transformed[:, :n], popmap["PopulationID"], test_size=0.3
            )
            lda.fit(X_train, y_train)
            y_pred = lda.predict(X_test)
            rmse = mean_squared_error(y_test, y_pred, squared=False)
            rmse_scores.append(rmse)

        plt.figure(figsize=(10, 6))
        sns.lineplot(x=n_components_range, y=rmse_scores)
        plt.xlabel("Number of Principal Components")
        plt.ylabel("Root Mean Squared Error")
        plt.title("DAPC Cross-Validation Results")
        plt.savefig("dapc_cv_results.png", bbox_inches="tight")
        plt.close()

    @staticmethod
    def plot_sfs(
        pop_gen_stats,
        population1,
        population2,
        savefig=True,
        show=False,
    ):
        """
        Plot a heatmap for the 2D SFS between two given populations and
        bar plots for the 1D SFS of each population.

        :param pop_gen_stats: An instance of the PopGenStatistics class
        :param population1: The name of the first population
        :param population2: The name of the second population
        :param savefig: Whether to save the figure to a file (default: True)
        :param show: Whether to show the figure inline (default: True)
        """
        sfs1 = pop_gen_stats.calculate_1d_sfs(population1)
        sfs2 = pop_gen_stats.calculate_1d_sfs(population2)
        sfs2d = pop_gen_stats.calculate_2d_sfs(population1, population2)

        fig, axs = plt.subplots(1, 3, figsize=(18, 6))
        sns.barplot(x=np.arange(1, len(sfs1) + 1), y=sfs1, ax=axs[0])
        axs[0].plot(np.arange(1, len(sfs1) + 1), sfs1, "k-")
        axs[0].set_title(f"1D SFS for {population1}")
        axs[0].xaxis.set_ticks(
            np.arange(0, len(sfs1) + 1, 5)
        )  # Set a step for displaying the tick labels
        axs[0].set_xticklabels(
            axs[0].get_xticks(), rotation=45
        )  # Rotate the tick labels

        sns.barplot(x=np.arange(1, len(sfs2) + 1), y=sfs2, ax=axs[1])
        axs[1].plot(np.arange(1, len(sfs2) + 1), sfs2, "k-")
        axs[1].set_title(f"1D SFS for {population2}")
        axs[1].xaxis.set_ticks(
            np.arange(0, len(sfs2) + 1, 5)
        )  # Set a step for displaying the tick labels
        axs[1].set_xticklabels(
            axs[1].get_xticks(), rotation=45
        )  # Rotate the tick labels

        colors = ["white", "green", "yellow", "orange", "red"]
        n_colors = len(colors)
        cmap = mpl_colors.LinearSegmentedColormap.from_list(
            "my_colormap", colors, N=n_colors * 10
        )

        sns.heatmap(sfs2d, cmap=cmap, ax=axs[2])
        axs[2].set_title(f"2D SFS for {population1} and {population2}")

        if savefig:
            plt.savefig(f"sfs_{population1}_{population2}.png")

        if show:
            plt.show()

    @staticmethod
    def plot_joint_sfs_grid(
        pop_gen_stats, populations, savefig=True, show=True
    ):
        """
        Plot the joint SFS between all possible pairs of populations in the popmap file
        in a grid layout.

        Args:
            pop_gen_stats (PopGenStatistics): An instance of the PopGenStatistics class.
            populations (list): A list of population names.
            savefig (bool, optional): Whether to save the figure to a file. Defaults to True.
            show (bool, optional): Whether to show the figure inline. Defaults to True.
        """
        n_populations = len(populations)
        n_cols = math.ceil(math.sqrt(n_populations))
        n_rows = math.ceil(n_populations / n_cols)

        fig, axs = plt.subplots(
            n_rows, n_cols, figsize=(4 * n_cols, 4 * n_rows)
        )

        for i, (pop1, pop2) in enumerate(
            itertools.combinations_with_replacement(populations, 2)
        ):
            row, col = divmod(i, n_cols)
            sfs2d = pop_gen_stats.calculate_2d_sfs(pop1, pop2)
            sns.heatmap(sfs2d, cmap="coolwarm", ax=axs[row, col], cbar=False)
            axs[row, col].set_title(f"Joint SFS for {pop1} and {pop2}")

        # Remove unused axes
        for j in range(i + 1, n_rows * n_cols):
            row, col = divmod(j, n_cols)
            fig.delaxes(axs[row, col])

        fig.tight_layout()

        if savefig:
            plt.savefig("joint_sfs_grid.png")

        if show:
            plt.show()

    @staticmethod
    def _plotly_sankey(nodes, links, outfile):
        # Prepare the data for the Sankey diagram
        link_colors = [
            "rgba(31, 119, 180, 0.8)",
            "rgba(255, 127, 14, 0.8)",
            "rgba(44, 160, 44, 0.8)",
            "rgba(214, 39, 40, 0.8)",
            "rgba(148, 103, 189, 0.8)",
            "rgba(140, 86, 75, 0.8)",
        ]

        for i, color in enumerate(link_colors):
            if i < len(links):
                links[i]["color"] = color

        # Create the Sankey diagram
        fig = go.Figure(
            go.Sankey(
                node=dict(
                    pad=15,
                    thickness=20,
                    line=dict(color="black", width=0.5),
                    label=[n["label"] for n in nodes],
                ),
                link=dict(
                    source=[l["source"] for l in links],
                    target=[l["target"] for l in links],
                    value=[l["value"] for l in links],
                    color=[
                        l.get("color", "rgba(0, 0, 0, 0.8)") for l in links
                    ],
                ),
            )
        )

        # Set the dimensions of the figure
        fig.update_layout(
            width=1600,  # Adjust the width
            height=1200,  # Adjust the height
            font=dict(size=24),
            title=dict(text="Filtering Report", x=0.5, y=0.95),
        )

        # Save the image to a file
        fig.write_image(outfile, scale=1.3, engine="kaleido")

    @classmethod
    def _calc_node_positions(
        cls,
        nodes: list,
        node_groups: list,
        level_arrangement: list,
        final_group_extra_gap: float = 0.05,
        y_sep: float = 0.3,
    ) -> Tuple[list, list]:
        final_group_extra_gap = 0.05
        normal_gap = (1 - final_group_extra_gap) / (len(node_groups) - 1)

        x_pos = [
            round(group_idx * normal_gap, 2)
            if group_idx < len(node_groups) - 1
            else round(group_idx * normal_gap + final_group_extra_gap, 2)
            for group_idx, group in enumerate(node_groups)
            for node_idx, node in enumerate(group)
        ]

        y_pos = []
        for group_idx, group in enumerate(node_groups):
            for node_idx, node in enumerate(group):
                if node in level_arrangement[0]:
                    y_pos.append(1)
                elif node in level_arrangement[1]:
                    y_pos.append(0.5)
                else:
                    y_pos.append(0)

        return x_pos, y_pos

    @staticmethod
    def plot_sankey_filtering_report(
        loci_removed_per_step,
        loci_before,
        loci_after,
        outfile,
        plot_dir="plots",
        included_steps=None,
    ):

        if included_steps is None:
            included_steps = list(range(6))

        steps = [
            ["Unfiltered", "Monomorphic", loci_removed_per_step[0][1]]
            if 0 in included_steps
            else None,
            [
                "Unfiltered",
                "Filter Singletons",
                loci_before - loci_removed_per_step[0][1],
            ]
            if 1 in included_steps
            else None,
            ["Filter Singletons", "Singletons", loci_removed_per_step[1][1]]
            if 2 in included_steps
            else None,
            [
                "Filter Singletons",
                "Filter Non-Biallelic",
                loci_before - sum([x[1] for x in loci_removed_per_step[0:2]]),
            ]
            if 3 in included_steps
            else None,
            [
                "Filter Non-Biallelic",
                "Non-Biallelic",
                loci_removed_per_step[2][1],
            ]
            if 4 in included_steps
            else None,
            [
                "Filter Non-Biallelic",
                "Filter Missing (Global)",
                loci_before - sum([x[1] for x in loci_removed_per_step[0:3]]),
            ]
            if 5 in included_steps
            else None,
            [
                "Filter Missing (Global)",
                "Missing (Global)",
                loci_removed_per_step[3][1],
            ]
            if 6 in included_steps
            else None,
            [
                "Filter Missing (Global)",
                "Filter Missing (Populations)",
                loci_before - sum([x[1] for x in loci_removed_per_step[0:4]]),
            ]
            if 7 in included_steps
            else None,
            [
                "Filter Missing (Populations)",
                "Missing (Populations)",
                loci_removed_per_step[4][1],
            ]
            if 8 in included_steps
            else None,
            [
                "Filter Missing (Populations)",
                "Filter MAF",
                loci_before - sum([x[1] for x in loci_removed_per_step[0:5]]),
            ]
            if 9 in included_steps
            else None,
            ["Filter MAF", "MAF", loci_removed_per_step[5][1]]
            if 10 in included_steps
            else None,
            ["Filter MAF", "Filtered", loci_after]
            if 11 in included_steps
            else None,
        ]

        steps = [step for step in steps if step is not None]

        l = []
        zeros = []
        node_labels = ["Unfiltered"]
        for step in steps:
            if step[2] > 0:
                l.append(step)
            else:
                zeros.append(step[2])

        df = pd.DataFrame(l, columns=["Source", "Target", "Count"])
        # Convert integer labels to strings
        df["Source"] = df["Source"].astype(str)
        df["Target"] = df["Target"].astype(str)

        node_labels = [
            "Unfiltered",
            "Monomorphic",
            "Filter Singletons",
            "Singletons",
            "Filter Non-Biallelic",
            "Non-Biallelic",
            "Filter Missing (Global)",
            "MAF",
            "Filter Missing (Populations)",
            "Missing (Global)",
            "Filter MAF",
            "Missing (Populations)",
            "Filtered",
        ]

        node_labels = [x for x in node_labels if x not in zeros]

        cmap = {
            "Unfiltered": "#66c2a5",
            "Filter Singletons": "#66c2a5",
            "Filter Non-Biallelic": "#66c2a5",
            "Filter Missing (Global)": "#66c2a5",
            "Filter Missing (Populations)": "#66c2a5",
            "Filter MAF": "#66c2a5",
            "Filtered": "#66c2a5",
            "Non-Biallelic": "#fc8d62",
            "Monomorphic": "#fc8d62",
            "Singletons": "#fc8d62",
            "Missing (Global)": "#fc8d62",
            "Missing (Populations)": "#fc8d62",
            "Missing (Sample)": "#fc8d62",
            "MAF": "#fc8d62",
        }

        # Add a new column 'LinkColor' to the dataframe
        df["LinkColor"] = df["Target"].apply(lambda x: cmap.get(x, "red"))

        sankey_plot = hv.Sankey(df, label="Sankey Filtering Report").options(
            node_color="blue",
            cmap=cmap,
            width=1000,
            height=500,
            edge_color="LinkColor",
            node_padding=40,
        )

        # Apply custom node labels
        label_array = np.array(node_labels)
        sankey_plot = sankey_plot.redim.values(Node=label_array)

        # Create custom legend
        legend = """
        <div style="position:absolute;right:20px;top:20px;border:1px solid black;padding:10px;background-color:white">
            <div style="display:flex;align-items:center;">
                <div style="width:20px;height:20px;background-color:#66c2a5;margin-right:5px;"></div>
                <div>Loci Remaining</div>
            </div>
            <div style="display:flex;align-items:center;">
                <div style="width:20px;height:20px;background-color:#fc8d62;margin-right:5px;"></div>
                <div>Loci Removed</div>
            </div>
        </div>
        """

        # Create the custom legend using hv.Div
        legend_plot = hv.Div(legend)

        # Convert the HoloViews objects to Bokeh models
        bokeh_sankey_plot = hv.render(sankey_plot)
        bokeh_legend_plot = hv.render(legend_plot)

        # Combine the Bokeh plots using Panel
        combined = pn.Row(bokeh_sankey_plot, bokeh_legend_plot)

        outfile_final = os.path.join(plot_dir, outfile)
        Path(plot_dir).mkdir(parents=True, exist_ok=True)

        # Save the plot to an HTML file
        combined.save(outfile_final)

    @staticmethod
    def plot_gt_distribution(df, plot_path):
        df = misc.validate_input_type(df, return_type="df")
        df_melt = pd.melt(df, value_name="Count")
        cnts = df_melt["Count"].value_counts()
        cnts.index.names = ["Genotype"]
        cnts = pd.DataFrame(cnts).reset_index()
        cnts.sort_values(by="Genotype", inplace=True)
        cnts["Genotype"] = cnts["Genotype"].astype(str)

        fig, ax = plt.subplots(1, 1, figsize=(15, 15))
        g = sns.barplot(x="Genotype", y="Count", data=cnts, ax=ax)
        g.set_xlabel("Integer-encoded Genotype")
        g.set_ylabel("Count")
        g.set_title("Genotype Counts")
        for p in g.patches:
            g.annotate(
                f"{p.get_height():.1f}",
                (p.get_x() + 0.25, p.get_height() + 0.01),
                xytext=(0, 1),
                textcoords="offset points",
                va="bottom",
            )

        fig.savefig(
            os.path.join(plot_path, "genotype_distributions.png"),
            bbox_inches="tight",
            facecolor="white",
        )
        plt.close()
