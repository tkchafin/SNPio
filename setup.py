from setuptools import setup, find_packages

setup(
    name="snpio",
    version="1.0.1.1",
    url="https://github.com/btmartin721/SNPio",
    author="Bradley T. Martin and Tyler K. Chafin",
    author_email="evobio721@gmail.com",
    description="Reads and writes VCF, PHYLIP, and STRUCTURE files and performs data filtering on the alignment.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    license="GPL3",
    keywords=[
        "genomics",
        "bioinformatics",
        "population genetics",
        "SNP",
        "VCF",
        "PHYLIP",
        "STRUCTURE",
        "missing data",
        "filtering",
        "MAF",
        "biallelic",
    ],
    platforms=["Any"],
    packages=find_packages(),
    include_package_data=True,
    python_requires=">=3.8",
    install_requires=[
        "biopython",
        "bokeh",
        "ete3",
        "holoviews",
        "kneed",
        "matplotlib",
        "numpy",
        "pandas",
        "panel",
        "plotly",
        "requests",
        # "cyvcf2",
        "scikit-learn",
        "scipy",
        "seaborn",
        "toytree",
        "kaleido",
        "psutil",
    ],
    extras_require={
        "docs": ["sphinx<7", "sphinx-rtd-theme", "sphinx-autodoc-typehints"],
        "intel": ["scikit-learn-intelex"],
    },
    entry_points={"console_scripts": ["snpio=run_snpio.py:main"]},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GPL3 License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    project_urls={
        "Source Code": "https://github.com/btmartin721/SNPio",
        "Bug Tracker": "https://github.com/btmartin721/SNPio/issues",
    },
)
