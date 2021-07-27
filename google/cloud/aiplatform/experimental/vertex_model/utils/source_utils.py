# -*- coding: utf-8 -*-

# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import inspect
from typing import Any


class SourceMaker:
    def __init__(self, cls_name: str):
        self.source = ["class {}:".format(cls_name)]

    def add_method(self, method_str: str):
        self.source.extend(method_str.split("\n"))


def _make_class_source(obj: Any) -> str:
    """Retrieves the source code for the class obj represents, usually an extension
       of VertexModel.

    Args:
        obj (Any): An instantiation of a user-written class
    """
    source_maker = SourceMaker(obj.__class__.__name__)

    for key, value in inspect.getmembers(obj):
        if inspect.ismethod(value) or inspect.isfunction(value):
            source_maker.add_method(inspect.getsource(value))

    return "\n".join(source_maker.source)


def _make_source(
    cls_source: str,
    cls_name: str,
    instance_method: str,
    pass_through_params,
    param_name_to_serialized_info,
    obj,
) -> str:
    """Converts a class source to a string including necessary imports.

    Args:
        cls_source (str): A string representing the source code of a user-written class.
        cls_name (str): The name of the class cls_source represents.
        instance_method (str): The method within the class that should be called from __main__

    Returns:
        A string representing a user-written class that can be written to a file in
        order to yield an inner script for the ModelBuilder SDK. The only difference
        between the user-written code and the string returned by this method is that
        the user has the option to specify a method to call from __main__.
    """
    src = "\n".join(
        [
            "import torch",
            "import pandas as pd",
            "from google.cloud.aiplatform import training_util",
            "from google.cloud.aiplatform.experimental.vertex_model.serializers import *",
            cls_source,
        ]
    )

    # First, add __main__ header
    src = src + "if __name__ == '__main__':\n"

    # Then, instantiate model
    class_args = inspect.signature(obj.__class__.__init__).bind(*args, **kwargs)
    class_args_arg = [locals()[arg] for arg in class_args.args]
    class_args_kwarg = [locals()[kwarg] for kwarg in class_args.kwargs]

    src = src + f"\tmodel = {cls_name}({class_args_arg}, {class_args_kwarg})\n"

    # Start function call
    src = src + f"\tmodel.{instance_method}("

    # Iterate through parameters:
    for (
        parameter_name,
        (parameter_uri, parameter_type),
    ) in param_name_to_serialized_info.items():
        deserializer = obj._data_serialization_mapping[parameter_type][0]

        # Can also make individual calls for each serialized parameter, but was unsure
        # for situations such as when a dataloader format is serialized.
        src = src + f"{parameter_name}={deserializer.__name__}({parameter_uri}), "

    for parameter_name, parameter_value in pass_through_params.items():
        src = src + f"{parameter_name}={parameter_value}, "

    src = src + ")\n"

    return src
