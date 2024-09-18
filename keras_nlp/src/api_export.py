# Copyright 2024 The KerasNLP Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import types

import keras

try:
    import namex
except ImportError:
    namex = None


def maybe_register_serializable(path, symbol):
    # If we have multiple export names, actually make sure to register these
    # first. This makes sure we have a backward compat mapping of old serialized
    # name to new class.
    if isinstance(path, (list, tuple)):
        for name in path:
            name = name.split(".")[-1]
            keras.saving.register_keras_serializable(
                package="keras_nlp", name=name
            )(symbol)
    if isinstance(symbol, types.FunctionType) or hasattr(symbol, "get_config"):
        # We register twice, first with the old name, second with the new name,
        # so loading still works under the old name.
        # TODO replace compat_package_name with keras-nlp after rename.
        compat_name = "compat_package_name"
        keras.saving.register_keras_serializable(package=compat_name)(symbol)
        keras.saving.register_keras_serializable(package="keras_nlp")(symbol)


if namex:

    class keras_nlp_export(namex.export):
        def __init__(self, path):
            super().__init__(package="keras_nlp", path=path)

        def __call__(self, symbol):
            maybe_register_serializable(self.path, symbol)
            return super().__call__(symbol)

else:

    class keras_nlp_export:
        def __init__(self, path):
            pass

        def __call__(self, symbol):
            maybe_register_serializable(symbol)
            return symbol
