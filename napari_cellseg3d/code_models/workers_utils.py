import typing as t
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import torch
from monai.transforms import MapTransform, Transform
from qtpy.QtCore import Signal
from superqt.utils._qthreading import WorkerBaseSignals
from tqdm import tqdm

# local
from napari_cellseg3d import interface as ui
from napari_cellseg3d import utils
from napari_cellseg3d.utils import LOGGER as logger

if TYPE_CHECKING:
    from napari_cellseg3d.code_models.instance_segmentation import ImageStats

PRETRAINED_WEIGHTS_DIR = Path(__file__).parent.resolve() / Path(
    "models/pretrained"
)


class WeightsDownloader:
    """A utility class the downloads the weights of a model when needed."""

    def __init__(self, log_widget: t.Optional[ui.Log] = None):
        """
        Creates a WeightsDownloader, optionally with a log widget to display the progress.

        Args:
            log_widget (log_utility.Log): a Log to display the progress bar in. If None, uses logger.info()
        """
        self.log_widget = log_widget

    def download_weights(self, model_name: str, model_weights_filename: str):
        """
        Downloads a specific pretrained model.
        This code is adapted from DeepLabCut with permission from MWMathis.

        Args:
            model_name (str): name of the model to download
            model_weights_filename (str): name of the .pth file expected for the model
        """
        import json
        import tarfile
        import urllib.request

        def show_progress(_, block_size, __):  # count, block_size, total_size
            pbar.update(block_size)

        logger.info("*" * 20)
        pretrained_folder_path = PRETRAINED_WEIGHTS_DIR
        json_path = pretrained_folder_path / Path("pretrained_model_urls.json")

        check_path = pretrained_folder_path / Path(model_weights_filename)

        if Path(check_path).is_file():
            message = f"Weight file {model_weights_filename} already exists, skipping download"
            if self.log_widget is not None:
                self.log_widget.print_and_log(message, printing=False)
            logger.info(message)
            return

        with Path.open(json_path) as f:
            neturls = json.load(f)
        if model_name in neturls:
            url = neturls[model_name]
            response = urllib.request.urlopen(url)

            start_message = f"Downloading the model from HuggingFace {url}...."
            total_size = int(response.getheader("Content-Length"))
            if self.log_widget is None:
                logger.info(start_message)
                pbar = tqdm(unit="B", total=total_size, position=0)
            else:
                self.log_widget.print_and_log(start_message)
                pbar = tqdm(
                    unit="B",
                    total=total_size,
                    position=0,
                    file=self.log_widget,
                )

            filename, _ = urllib.request.urlretrieve(
                url, reporthook=show_progress
            )
            with tarfile.open(filename, mode="r:gz") as tar:

                def is_within_directory(directory, target):
                    abs_directory = Path(directory).resolve()
                    abs_target = Path(target).resolve()
                    # prefix = os.path.commonprefix([abs_directory, abs_target])
                    logger.debug(abs_directory)
                    logger.debug(abs_target)
                    logger.debug(abs_directory.parents)

                    return abs_directory in abs_target.parents

                def safe_extract(
                    tar, path=".", members=None, *, numeric_owner=False
                ):
                    for member in tar.getmembers():
                        member_path = str(Path(path) / member.name)
                        if not is_within_directory(path, member_path):
                            raise Exception(
                                "Attempted Path Traversal in Tar File"
                            )

                    tar.extractall(path, members, numeric_owner=numeric_owner)

                safe_extract(tar, pretrained_folder_path)
                # tar.extractall(pretrained_folder_path)
        else:
            raise ValueError(
                f"Unknown model: {model_name}. Should be one of {', '.join(neturls)}"
            )


class LogSignal(WorkerBaseSignals):
    """Signal to send messages to be logged from another thread.

    Separate from Worker instances as indicated `on this post`_

    .. _on this post: https://stackoverflow.com/questions/2970312/pyqt4-qtcore-pyqtsignal-object-has-no-attribute-connect
    """  # TODO link ?

    log_signal = Signal(str)
    """qtpy.QtCore.Signal: signal to be sent when some text should be logged"""
    warn_signal = Signal(str)
    """qtpy.QtCore.Signal: signal to be sent when some warning should be emitted in main thread"""
    error_signal = Signal(Exception, str)
    """qtpy.QtCore.Signal: signal to be sent when some error should be emitted in main thread"""

    # Should not be an instance variable but a class variable, not defined in __init__, see
    # https://stackoverflow.com/questions/2970312/pyqt4-qtcore-pyqtsignal-object-has-no-attribute-connect

    def __init__(self):
        super().__init__()


class ONNXModelWrapper(torch.nn.Module):
    """Class to replace torch model by ONNX Runtime session"""

    def __init__(self, file_location):
        super().__init__()
        try:
            import onnxruntime as ort
        except ImportError as e:
            logger.error("ONNX is not installed but ONNX model was loaded")
            logger.error(e)
            msg = "PLEASE INSTALL ONNX CPU OR GPU USING pip install napari-cellseg3d[onnx-cpu] OR napari-cellseg3d[onnx-gpu]"
            logger.error(msg)
            raise ImportError(msg) from e

        self.ort_session = ort.InferenceSession(
            file_location,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )

    def forward(self, modeL_input):
        """Wraps ONNX output in a torch tensor"""
        outputs = self.ort_session.run(
            None, {"input": modeL_input.cpu().numpy()}
        )
        return torch.tensor(outputs[0])

    def eval(self):
        """Dummy function to replace model.eval()"""
        pass

    def to(self, device):
        """Dummy function to replace model.to(device)"""
        pass


class QuantileNormalizationd(MapTransform):
    def __init__(self, keys, allow_missing_keys: bool = False):
        super().__init__(keys, allow_missing_keys)

    def __call__(self, data):
        d = dict(data)
        for key in self.keys:
            d[key] = self.normalizer(d[key])
        return d

    def normalizer(self, image: torch.Tensor):
        """Normalize each image in a batch individually by quantile normalization."""
        if image.ndim == 4:
            for i in range(image.shape[0]):
                image[i] = utils.quantile_normalization(image[i])
        else:
            raise NotImplementedError(
                "QuantileNormalizationd only supports 2D and 3D tensors with NCHWD format"
            )
        return image


class QuantileNormalization(Transform):
    def __call__(self, img):
        return utils.quantile_normalization(img)


@dataclass
class InferenceResult:
    """Class to record results of a segmentation job"""

    image_id: int = 0
    original: np.array = None
    instance_labels: np.array = None
    crf_results: np.array = None
    stats: "np.array[ImageStats]" = None
    result: np.array = None
    model_name: str = None


@dataclass
class TrainingReport:
    show_plot: bool = True
    epoch: int = 0
    loss_values: t.Dict = None  # TODO(cyril) : change to dict and unpack different losses for e.g. WNet with several losses
    validation_metric: t.List = None
    weights: np.array = None
    images: t.List[np.array] = None
