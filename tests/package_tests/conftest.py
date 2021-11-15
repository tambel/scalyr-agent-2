import argparse


def pytest_addoption(parser):
    parser.addoption(
        "--spec", dest="test_spec_name", action="append", required=True, default=list()
    )