"""Type annotations must not hide executable methods from coverage measurement."""

import re

from coverage import Coverage


def test_coverage_excludes_protocol_stubs_but_not_tuple_ellipsis_annotations():
    patterns = Coverage(config_file="pyproject.toml").get_exclude_list()

    def excluded(line):
        return any(re.search(pattern, line) for pattern in patterns)

    assert excluded("    ...")
    assert excluded("    ) -> dict[str, object]: ...")
    assert not excluded("    requests: tuple[QuoteRequest, ...],")
    assert not excluded("    def get_quotes(self, ids: tuple[UUID, ...]):")
