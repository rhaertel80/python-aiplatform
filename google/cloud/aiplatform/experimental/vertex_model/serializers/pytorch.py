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

import functools
import pathlib
import tempfile
from typing import Optional

from google.cloud import storage
from google.cloud.aiplatform import initializer
from google.cloud.aiplatform import utils
from google.cloud.aiplatform.experimental.vertex_model.serializers import (
    serializer_utils,
)

try:
    import torch
    from torch.utils.data import DataLoader
except ImportError:
    raise ImportError(
        "PyTorch is not installed. Please install torch to use VertexModel"
    )


def _serialize_remote_dataloader(
    artifact_uri: str,
    dataloader_path: Optional[str],
    obj: torch.utils.data.DataLoader,
    dataset_type: str,
) -> (str, str):
    """Serializes DataLoader object to GCS and stores remotely-sourced data in
       a run-time bucket

    Args:
        artifact_uri (str): the GCS bucket where the serialized object will reside.
        dataloader_path (str): the path where the origin data used to construct the DataLoader
                               resides.
        obj (torch.utils.data.DataLoader): the pytorch DataLoader to serialize.
        dataset_type (str): the intended use of the dataset (ie. training, testing)

    Returns:
        The GCS path pointing to the serialized DataLoader, the GCS path pointing to the
        serialized origin data.
    """

    # TODO(b/195442091): Check if uri is actually a local path and write to a local
    #                    location if that is the case.

    # Retrieve the source and blob names from the artifact URI
    (
        destination_bucket_name,
        destination_blob_prefix,
    ) = utils.extract_bucket_and_prefix_from_gcs_path(artifact_uri)

    path = serializer_utils.serialize_to_tmp_and_copy_to_gcs(
        "my_" + dataset_type + "_dataloader.pth",
        destination_bucket_name,
        destination_blob_prefix,
        functools.partial(torch.save, obj),
    )

    return path, dataloader_path


def _serialize_local_dataloader(
    artifact_uri: str,
    dataloader_path: str,
    obj: torch.utils.data.DataLoader,
    dataset_type: str,
) -> (str, str):
    """Serializes DataLoader object to GCS and stores locally-sourced data in
       a run-time bucket

    Args:
        artifact_uri (str): the GCS bucket where the serialized object will reside.
        dataloader_path (str): the path where the origin data used to construct the DataLoader
                               resides.
        obj (torch.utils.data.DataLoader): the pytorch DataLoader to serialize.
        dataset_type (str): the intended use of the dataset (ie. training, testing)

    Returns:
        The GCS path pointing to the serialized DataLoader, the GCS path pointing to the
        serialized origin data.
    """

    if not artifact_uri.startswith("gs://"):
        local_path = artifact_uri + "my_" + dataset_type + "_dataloader.pth"
        torch.save(obj, local_path)
        return local_path, dataloader_path

    gcs_bucket, gcs_blob_prefix = utils.extract_bucket_and_prefix_from_gcs_path(
        artifact_uri
    )

    if dataloader_path:
        dataloader_path = pathlib.Path(dataloader_path)
        data_blob_path = dataset_type + "_" + dataloader_path.name

        if gcs_blob_prefix:
            data_blob_path = "/".join([gcs_blob_prefix, data_blob_path])

        client = storage.Client(
            project=initializer.global_config.project,
            credentials=initializer.global_config.credentials,
        )

        bucket = client.bucket(gcs_bucket)
        data_blob = bucket.blob(data_blob_path)
        data_blob.upload_from_filename(str(dataloader_path))

        data_gcs_path = "".join(
            ["gs://", "/".join([data_blob.bucket.name, data_blob.name])]
        )
    else:
        data_gcs_path = None

    path = serializer_utils.serialize_to_tmp_and_copy_to_gcs(
        "my_" + dataset_type + "_dataloader.pth",
        gcs_bucket,
        gcs_blob_prefix,
        functools.partial(torch.save, obj),
    )

    return path, data_gcs_path


def _serialize_dataloader(
    artifact_uri: str, obj: torch.utils.data.DataLoader, dataset_type: str
) -> (str, str):
    """Serializes DataLoader object to GCS and stores remotely-sourced data in
       a run-time bucket. Determines which helper method to use by introspecting
       the user-specified DataLoader object.

    Args:
        artifact_uri (str): the GCS bucket where the serialized object will reside.
        obj (torch.utils.data.DataLoader): the DataLoader to be serialized
        dataset_type (str): the intended use of the dataset (ie. training, testing)

    Returns:
        The GCS path pointing to the serialized DataLoader, the GCS path pointing to the
        serialized origin data.
    """
    my_dataset = obj.dataset
    root = getattr(my_dataset, "root", None)

    # Decide whether to pass to remote or local serialization
    if root and root.startswith("gs://"):
        return _serialize_remote_dataloader(artifact_uri, root, obj, dataset_type)
    else:
        return _serialize_local_dataloader(artifact_uri, root, obj, dataset_type)


def _deserialize_dataloader(artifact_uri: str) -> DataLoader:
    """Deserializes DataLoader object from a GCS uri

    Args:
        artifact_uri (str): the GCS bucket where the serialized object will resides

    Returns:
        The DataLoader object stored at the given location.
    """

    if not artifact_uri.startswith("gs://"):
        dataloader = torch.load(artifact_uri)
        return dataloader

    gcs_bucket, gcs_blob = utils.extract_bucket_and_prefix_from_gcs_path(artifact_uri)

    client = storage.Client(
        project=initializer.global_config.project,
        credentials=initializer.global_config.credentials,
    )

    bucket = client.bucket(gcs_bucket)
    blob = bucket.blob(gcs_blob)
    dataloader = None

    # This code may not be necessary, as torch may be able to read from a remote path, but
    # I need to double check this.
    try:
        with tempfile.TemporaryDirectory() as tmpdirname:
            dest_file = pathlib.Path(tmpdirname) / "deserialized_dataloader.pth"
            blob.download_to_filename(dest_file)
            dataloader = torch.load(dest_file)

    except (ValueError, RuntimeError) as err:
        raise RuntimeError(
            "There was a problem reading the model at '{}': {}".format(
                artifact_uri, err
            )
        )

    # Return a pandas DataFrame read from the csv in the cloud
    return dataloader
