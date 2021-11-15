import argparse
import pathlib as pl
import sys

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(__SOURCE_ROOT__))


from tests.package_tests import current_test_specifications


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("test_spec_name")
    parser.add_argument("--package-path", required=True)
    parser.add_argument("--scalyr-api-key", required=True)

    args = parser.parse_args()
    package_test_spec = current_test_specifications.PackageTestSpec.ALL_TEST_SPECS[args.test_spec_name]

    package_test_spec.base_spec.run_test_locally(
        package_path=pl.Path(args.package_path),
        scalyr_api_key=args.scalyr_api_key
    )