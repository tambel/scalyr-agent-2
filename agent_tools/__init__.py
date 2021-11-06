import pathlib as pl
import shutil


from agent_tools import build_and_test_specs


def build_package_from_spec(
        package_build_name: str,
        output_path_dir: str,
        locally: bool = False,
        variant: str = None,
        no_versioned_file_name: bool = False
):
    output_path = pl.Path(output_path_dir)
    package_build_spec = build_and_test_specs.PACKAGE_BUILD_SPECS[package_build_name]
    if output_path.exists():
        shutil.rmtree(output_path)
    output_path.mkdir(parents=True)

    package_builder_cls = package_build_spec.package_builder_cls
    package_builder = package_builder_cls(
        architecture=package_build_spec.architecture,
        variant=variant, no_versioned_file_name=no_versioned_file_name
    )
    package_builder.build(
        output_path=output_path,
    )