from setuptools import setup, find_packages
setup(
    name="samsara-loop",
    version="0.1.0",
    description="Agent feedback loop engine — capture failures, generate tests, self-evaluate",
    author="Anand Inbasekaran",
    license="MIT",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=["pydantic>=2.0", "flask>=3.0"],
    extras_require={"dev": ["pytest"]},
    entry_points={
        "console_scripts": [
            "samsara-loop=samsara_loop.cli.cli:main",
        ],
    },
)
