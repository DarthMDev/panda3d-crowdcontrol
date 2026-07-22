from pathlib import Path

from setuptools import setup, find_packages

ROOT = Path(__file__).parent

setup(
    name="panda3d-crowdcontrol",
    version="0.1.0",
    description="Crowd Control SimpleTCP integration for Panda3D games",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="DarthMDev",
    license="MIT",
    license_files=["LICENSE"],
    url="https://github.com/DarthMDev/panda3d-crowdcontrol",
    project_urls={"Issues": "https://github.com/DarthMDev/panda3d-crowdcontrol/issues"},
    packages=find_packages(include=["panda3d_crowdcontrol", "panda3d_crowdcontrol.*"]),
    install_requires=[
        "panda3d>=1.10.15",
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Topic :: Games/Entertainment",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.8",
)
