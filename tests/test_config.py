import copy

import jsonschema
import pytest

from software.config import validate_config


def test_default_config_valid(cfg):
    validate_config(cfg)


def test_missing_vs_nominal_raises(cfg):
    bad = copy.deepcopy(cfg)
    del bad["vs_nominal_v"]
    with pytest.raises(jsonschema.ValidationError):
        validate_config(bad)


def test_wrong_type_sample_rate_raises(cfg):
    bad = copy.deepcopy(cfg)
    bad["sample_rate_hz"] = "500"
    with pytest.raises(jsonschema.ValidationError):
        validate_config(bad)


def test_bad_filter_placement_raises(cfg):
    bad = copy.deepcopy(cfg)
    bad["filter_placement"] = "middle"
    with pytest.raises(jsonschema.ValidationError):
        validate_config(bad)
