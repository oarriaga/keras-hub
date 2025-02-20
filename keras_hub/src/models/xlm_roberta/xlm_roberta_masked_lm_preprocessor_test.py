import os

import pytest

from keras_hub.src.models.xlm_roberta.xlm_roberta_masked_lm_preprocessor import (  # noqa: E501
    XLMRobertaMaskedLMPreprocessor,
)
from keras_hub.src.models.xlm_roberta.xlm_roberta_tokenizer import (
    XLMRobertaTokenizer,
)
from keras_hub.src.tests.test_case import TestCase


class XLMRobertaMaskedLMPreprocessorTest(TestCase):
    def setUp(self):
        self.tokenizer = XLMRobertaTokenizer(
            # Generated using create_xlm_roberta_test_proto.py
            proto=os.path.join(
                self.get_test_data_dir(), "xlm_roberta_test_vocab.spm"
            )
        )
        self.init_kwargs = {
            "tokenizer": self.tokenizer,
            # Simplify our testing by masking every available token.
            "mask_selection_rate": 1.0,
            "mask_token_rate": 1.0,
            "random_token_rate": 0.0,
            "mask_selection_length": 4,
            "sequence_length": 12,
        }
        self.input_data = ["the quick brown fox"]

    def test_preprocessor_basics(self):
        self.run_preprocessor_test(
            cls=XLMRobertaMaskedLMPreprocessor,
            init_kwargs=self.init_kwargs,
            input_data=self.input_data,
            expected_output=(
                {
                    "token_ids": [[0, 13, 13, 13, 13, 2, 1, 1, 1, 1, 1, 1]],
                    "padding_mask": [[1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0]],
                    "mask_positions": [[1, 2, 3, 4]],
                },
                [[6, 11, 7, 9]],
                [[1.0, 1.0, 1.0, 1.0]],
            ),
        )

    def test_no_masking_zero_rate(self):
        no_mask_preprocessor = XLMRobertaMaskedLMPreprocessor(
            self.tokenizer,
            mask_selection_rate=0.0,
            mask_selection_length=4,
            sequence_length=12,
        )
        input_data = ["the quick brown fox"]
        self.assertAllClose(
            no_mask_preprocessor(input_data),
            (
                {
                    "token_ids": [[0, 6, 11, 7, 9, 2, 1, 1, 1, 1, 1, 1]],
                    "padding_mask": [[1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0]],
                    "mask_positions": [[0, 0, 0, 0]],
                },
                [[0, 0, 0, 0]],
                [[0.0, 0.0, 0.0, 0.0]],
            ),
        )

    @pytest.mark.extra_large
    def test_all_presets(self):
        for preset in XLMRobertaMaskedLMPreprocessor.presets:
            self.run_preset_test(
                cls=XLMRobertaMaskedLMPreprocessor,
                preset=preset,
                input_data=self.input_data,
            )
