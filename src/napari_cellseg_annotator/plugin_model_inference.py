import os
import warnings
from pathlib import Path

import napari
import numpy as np
import torch
from monai.data import Dataset
from monai.data import DataLoader
# MONAI
from monai.inferers import sliding_window_inference
from monai.transforms import AsDiscrete
from monai.transforms import Compose
from monai.transforms import EnsureChannelFirstd
from monai.transforms import EnsureType
from monai.transforms import EnsureTyped
from monai.transforms import LoadImaged
from monai.transforms import SpatialPadd
from monai.transforms import Zoom
from napari.qt.threading import thread_worker
# Qt
from qtpy.QtWidgets import QCheckBox
from qtpy.QtWidgets import QDoubleSpinBox
from qtpy.QtWidgets import QGroupBox
from qtpy.QtWidgets import QLabel
from qtpy.QtWidgets import QLayout
from qtpy.QtWidgets import QPushButton
from qtpy.QtWidgets import QSizePolicy
from qtpy.QtWidgets import QSpinBox
from qtpy.QtWidgets import QVBoxLayout
from qtpy.QtWidgets import QWidget
from tifffile import imwrite

# local
from napari_cellseg_annotator import utils
from napari_cellseg_annotator.model_framework import ModelFramework

WEIGHTS_DIR = os.path.dirname(os.path.realpath(__file__)) + str(
    Path("/models/saved_weights")
)


class Inferer(ModelFramework):
    """A plugin to run already trained models in evaluation mode to preform inference and output a label on all
    given volumes."""

    def __init__(self, viewer: "napari.viewer.Viewer"):
        """
        Creates an Inference loader plugin with the following widgets :

        * I/O :
            * A file extension choice for the images to load from selected folders

            * Two buttons to choose the images folder to run segmentation and save results in, respectively

        * Post-processing :
            * A box to select if data is anisotropic, if checked, asks for resolution in micron for each axis

            * A box to choose whether to threshold, if checked asks for a threshold between 0 and 1

        * Display options :
            * A dropdown menu to select which model should be used for inference

            * A checkbox to choose whether to display results in napari afterwards. Will ask for how many results to display, capped at 10

        * A button to launch the inference process

        * A button to close the widget

        TODO:

        * Verify if way of loading model is  OK

        * Padding OK ?

        * Save toggle ?

        Args:
            viewer (napari.viewer.Viewer): napari viewer to display the widget in
        """
        super().__init__(viewer)

        self._viewer = viewer

        self.worker = None
        """Worker for inference"""

        self.transforms = None

        self.show_res = False
        self.show_res_nbr = 1
        self.show_original = True
        self.zoom = [1, 1, 1]

        ############################
        ############################
        ############################
        ############################
        # TEST TODO REMOVE
        import glob

        directory = "C:/Users/Cyril/Desktop/test/test"

        # self.data_path = directory

        self.images_filepaths = sorted(
            glob.glob(os.path.join(directory, "*.tif"))
        )
        self.results_path = "C:/Users/Cyril/Desktop/test"
        #######################
        #######################
        #######################

        ###########################
        # interface

        # self.lbl_view = QLabel("View results in napari ?", self)

        self.view_checkbox = QCheckBox("View results in napari")
        self.view_checkbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.view_checkbox.stateChanged.connect(self.toggle_display_number)
        # self.lbl_view = QLabel("View results in napari ?", self)

        self.display_number_choice = QSpinBox()
        self.display_number_choice.setRange(1, 10)
        self.display_number_choice.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Fixed
        )
        self.lbl_display_number = QLabel("How many ? (max. 10)", self)

        self.aniso_checkbox = QCheckBox("Anisotropic data")
        self.aniso_checkbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.aniso_checkbox.stateChanged.connect(self.toggle_display_aniso)
        # self.lbl_aniso = QLabel("Anisotropic dataset ?", self)

        def make_anisotropy_choice(ax):
            widget = QDoubleSpinBox()
            widget.setMinimum(1)
            widget.setMaximum(10)
            widget.setValue(1.5)
            widget.setSingleStep(1.0)
            return widget

        self.aniso_box_widgets = [make_anisotropy_choice(ax) for ax in "xyz"]
        self.aniso_box_lbl = [
            QLabel("Resolution in " + axis + " (microns) :") for axis in "xyz"
        ]

        self.aniso_box_widgets[-1].setValue(5.0)

        for w in self.aniso_box_widgets:
            w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.aniso_resolutions = []

        self.thresholding_checkbox = QCheckBox("Perform thresholding")
        self.thresholding_checkbox.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Fixed
        )
        self.thresholding_checkbox.stateChanged.connect(
            self.toggle_display_thresh
        )

        self.thresholding_count = QDoubleSpinBox()
        self.thresholding_count.setMinimum(0)
        self.thresholding_count.setMaximum(1)
        self.thresholding_count.setSingleStep(0.05)
        self.thresholding_count.setValue(0.7)

        self.show_original_checkbox = QCheckBox("Show originals")
        self.show_original_checkbox.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Fixed
        )

        self.btn_start = QPushButton("Start inference")
        self.btn_start.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_start.clicked.connect(self.start)

        # hide unused widgets from parent class
        self.btn_label_files.setVisible(False)
        self.lbl_label_files.setVisible(False)
        self.btn_model_path.setVisible(False)
        self.lbl_model_path.setVisible(False)

        self.build()

    @staticmethod
    def create_inference_dict(images_filepaths):
        """Create a dict with all image paths in :py:attr:`~self.images_filepaths`

        Returns:
            dict: list of image paths from loaded folder"""
        data_dicts = [{"image": image_name} for image_name in images_filepaths]
        return data_dicts

    def check_ready(self):
        """Checks if the paths to the files are properly set"""
        if (
            self.images_filepaths != [""]
            and self.images_filepaths != []
            and self.results_path != ""
        ):
            return True
        else:
            warnings.formatwarning = utils.format_Warning
            warnings.warn("Image and label paths are not correctly set")
            return False

    def toggle_display_number(self):
        """Shows the choices for viewing results depending on whether :py:attr:`self.view_checkbox` is checked"""
        if self.view_checkbox.isChecked():
            self.display_number_choice.setVisible(True)
            self.lbl_display_number.setVisible(True)
            self.show_original_checkbox.setVisible(True)
        else:
            self.display_number_choice.setVisible(False)
            self.lbl_display_number.setVisible(False)
            self.show_original_checkbox.setVisible(False)

    def toggle_display_aniso(self):
        """Shows the choices for correcting anisotropy when viewing results depending on whether :py:attr:`self.aniso_checkbox` is checked"""
        if self.aniso_checkbox.isChecked():
            for w, lbl in zip(self.aniso_box_widgets, self.aniso_box_lbl):
                w.setVisible(True)
                lbl.setVisible(True)
        else:
            for w, lbl in zip(self.aniso_box_widgets, self.aniso_box_lbl):
                w.setVisible(False)
                lbl.setVisible(False)

    def toggle_display_thresh(self):
        """Shows the choices for thresholding results depending on whether :py:attr:`self.thresholding_checkbox` is checked"""
        if self.thresholding_checkbox.isChecked():
            self.thresholding_count.setVisible(True)
        else:
            self.thresholding_count.setVisible(False)

    def build(self):
        """Puts all widgets in a layout and adds them to the napari Viewer"""

        tab = QWidget()
        tab_layout = QVBoxLayout()
        tab_layout.setContentsMargins(0, 0, 1, 1)
        tab_layout.setSizeConstraint(QLayout.SetFixedSize)

        L, T, R, B = 7, 20, 7, 11  # margins for group boxes
        #################################
        #################################
        io_group = QGroupBox("I/O")
        io_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        io_layout = QVBoxLayout()
        io_layout.setContentsMargins(L, T, R, B)
        io_layout.setSizeConstraint(QLayout.SetFixedSize)

        io_layout.addWidget(
            utils.combine_blocks(self.filetype_choice, self.lbl_filetype),
            alignment=utils.LEFT_AL,
        )  # file extension
        io_layout.addWidget(
            utils.combine_blocks(self.btn_image_files, self.lbl_image_files),
            alignment=utils.LEFT_AL,
        )  # in folder
        io_layout.addWidget(
            utils.combine_blocks(self.btn_result_path, self.lbl_result_path),
            alignment=utils.LEFT_AL,
        )  # out folder

        io_group.setLayout(io_layout)
        tab_layout.addWidget(io_group, alignment=utils.LEFT_AL)
        #################################
        utils.add_blank(self, tab_layout)
        #################################
        #################################
        model_param_group = QGroupBox("Model choice")
        model_param_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        model_param_layout = QVBoxLayout()
        model_param_layout.setContentsMargins(L, T, R, B)
        model_param_layout.setSizeConstraint(QLayout.SetFixedSize)

        model_param_layout.addWidget(
            # utils.combine_blocks(
            self.model_choice,  # , self.lbl_model_choice, horizontal=False),
            alignment=utils.LEFT_AL,
        )  # model choice
        self.lbl_model_choice.setVisible(False)

        model_param_group.setLayout(model_param_layout)
        tab_layout.addWidget(model_param_group)
        #################################
        utils.add_blank(self, tab_layout)
        #################################
        #################################
        post_proc_group = QGroupBox("Post-processing")
        post_proc_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        post_proc_layout = QVBoxLayout()
        post_proc_layout.setContentsMargins(L, T, R, B)
        post_proc_layout.setSizeConstraint(QLayout.SetFixedSize)

        post_proc_layout.addWidget(
            self.aniso_checkbox, alignment=utils.LEFT_AL
        )

        [
            post_proc_layout.addWidget(widget, alignment=utils.LEFT_AL)
            for wdgts in zip(self.aniso_box_lbl, self.aniso_box_widgets)
            for widget in wdgts
        ]
        for w in self.aniso_box_widgets:
            w.setVisible(False)
        for w in self.aniso_box_lbl:
            w.setVisible(False)
        # anisotropy
        utils.add_blank(post_proc_group, post_proc_layout)

        post_proc_layout.addWidget(
            self.thresholding_checkbox, alignment=utils.LEFT_AL
        )
        post_proc_layout.addWidget(
            self.thresholding_count, alignment=utils.CENTER_AL
        )
        self.thresholding_count.setVisible(False)  # thresholding

        post_proc_group.setLayout(post_proc_layout)
        tab_layout.addWidget(post_proc_group, alignment=utils.LEFT_AL)
        ###################################
        utils.add_blank(self, tab_layout)
        ###################################
        ###################################
        display_opt_group = QGroupBox("Display options")
        display_opt_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        display_opt_layout = QVBoxLayout()
        display_opt_layout.setContentsMargins(L, T, R, B)
        display_opt_layout.setSizeConstraint(QLayout.SetFixedSize)

        display_opt_layout.addWidget(
            self.view_checkbox,  # utils.combine_blocks(self.view_checkbox, self.lbl_view),
            alignment=utils.LEFT_AL,
        )  # view_after bool
        display_opt_layout.addWidget(
            self.lbl_display_number, alignment=utils.LEFT_AL
        )
        display_opt_layout.addWidget(
            self.display_number_choice,
            alignment=utils.LEFT_AL,
        )  # number of results to display
        display_opt_layout.addWidget(
            self.show_original_checkbox,
            alignment=utils.LEFT_AL,
        )  # show original bool
        self.show_original_checkbox.toggle()

        self.display_number_choice.setVisible(False)
        self.show_original_checkbox.setVisible(False)
        self.lbl_display_number.setVisible(False)

        # TODO : add custom model handling ? using exec() to read user provided model class
        # self.lbl_label.setText("model.pth directory :")

        display_opt_group.setLayout(display_opt_layout)
        tab_layout.addWidget(display_opt_group)
        ###################################
        utils.add_blank(self, tab_layout)
        ###################################
        ###################################
        tab_layout.addWidget(self.btn_start, alignment=utils.LEFT_AL)
        tab_layout.addWidget(self.btn_close, alignment=utils.LEFT_AL)
        ###################################
        utils.make_scrollable(
            containing_widget=tab,
            contained_layout=tab_layout,
            base_wh=[100, 500],
        )
        self.addTab(tab, "Inference")

    def start(self):
        """Start the inference process, enables :py:attr:`~self.worker` and does the following:

        * Checks if the output and input folders are correctly set

        * Loads the weights from the chosen model

        * Creates a dict with all image paths (see :py:func:`~create_inference_dict`)

        * Loads the images, pads them so their size is a power of two in every dim (see :py:func:`utils.get_padding_dim`)

        * Performs sliding window inference (from MONAI) on every image

        * Saves all outputs in the selected results folder

        * If the option has been selected, display the results in napari, up to the maximum number selected
        """

        if not self.check_ready():
            err = "Aborting, please choose correct paths"
            self.print_and_log(err)
            raise ValueError(err)

        if self.worker is not None:
            if self.worker.is_running:
                pass
            else:
                self.worker.start()
                self.btn_start.setText("Running... Click to stop")
        else:
            self.print_and_log("Starting...")
            self.print_and_log("*" * 20)

            device = self.get_device()

            model_key = self.model_choice.currentText()
            model_dict = {  # gather model info
                "name": model_key,
                "class": self.get_model(model_key),
                "instance": self.get_model(model_key).get_net(),
            }

            weights = self.get_model(model_key).get_weights_file()

            if self.aniso_checkbox.isChecked():
                self.aniso_resolutions = [
                    w.value() for w in self.aniso_box_widgets
                ]
                self.zoom = utils.anisotropy_zoom_factor(
                    self.aniso_resolutions
                )
            else:
                self.zoom = [1, 1, 1]

            self.transforms = {
                "thresh": [
                    self.thresholding_checkbox.isChecked(),
                    self.thresholding_count.value(),
                ],
                "zoom": [
                    self.aniso_checkbox.isChecked(),
                    self.zoom,
                ],
            }

            self.worker = self.inference(
                device=device,
                model_dict=model_dict,
                weights=weights,
                images_filepaths=self.images_filepaths,
                results_path=self.results_path,
                filetype=self.filetype_choice.currentText(),
                transforms=self.transforms,
                logging=lambda text: self.worker_print_and_log(self, text),
            )
            # print("impath")
            # print(self.images_filepaths)

            self.worker.started.connect(self.on_start)

            self.show_res_nbr = self.display_number_choice.value()

            yield_connect_show_res = lambda data: self.on_yield(
                data,
                widget=self,
            )
            self.worker.yielded.connect(yield_connect_show_res)
            self.worker.errored.connect(yield_connect_show_res)

            self.worker.finished.connect(self.on_finish)

            if self.get_device(show=False) == "cuda":
                self.worker.finished.connect(self.empty_cuda_cache)
            self.btn_close.setVisible(False)

        if self.worker.is_running:  # if worker is running, tries to stop
            self.print_and_log(
                "Stop request, waiting for next inference & saving to occur..."
            )
            self.btn_start.setText("Stopping...")
            self.worker.quit()
        else:  # once worker is started, update buttons
            self.worker.start()
            self.btn_start.setText("Running...  Click to stop")

    def on_start(self):
        """Catches start signal from worker to call :py:func:`~display_status_report`"""
        self.display_status_report()

        self.show_res = self.view_checkbox.isChecked()
        self.show_original = self.show_original_checkbox.isChecked()
        self.print_and_log(f"Worker started at {utils.get_time()}")
        self.print_and_log(f"Saving results to : {self.results_path}")
        self.print_and_log("Worker is running...")

    def on_error(self):
        """Catches errors and tries to clean up. TODO : upgrade"""
        self.print_and_log("Worker errored...")
        self.print_and_log("Trying to clean up...")
        self.btn_start.setText("Start")
        self.btn_close.setVisible(True)

        self.worker = None
        self.empty_cuda_cache()

    def on_finish(self):
        """Catches finished signal from worker, resets workspace for next run."""
        self.print_and_log(f"\nWorker finished at {utils.get_time()}")
        self.print_and_log("*" * 20)
        self.btn_start.setText("Start")
        self.btn_close.setVisible(True)

        self.worker = None
        self.empty_cuda_cache()

    @staticmethod
    def on_yield(data, widget):
        """
        Displays the inference results in napari as long as data["image_id"] is lower than nbr_to_show,
        and updates the status report docked widget (namely the progress bar)

        Args:
            data (dict): dict yielded by :py:func:`~inference()`, contains : "image_id" : index of the returned image, "original" : original volume used for inference, "result" : inference result
            widget (QWidget): widget for accessing attributes
        """
        # check that viewer checkbox is on and that max number of displays has not been reached.
        image_id = data["image_id"]
        model_name = data["model_name"]
        total = len(widget.images_filepaths)

        viewer = widget._viewer

        widget.progress.setValue(100 * (image_id) // total)

        if widget.show_res and image_id <= widget.show_res_nbr:

            zoom = widget.zoom

            print(data["original"].shape)
            print(data["result"].shape)

            viewer.dims.ndisplay = 3
            viewer.scale_bar.visible = True

            if widget.show_original:
                original_layer = viewer.add_image(
                    data["original"],
                    colormap="inferno",
                    name=f"original_{image_id}",
                    scale=zoom,
                    opacity=0.7,
                )

            out_colormap = "twilight"
            if widget.transforms["thresh"][0]:
                out_colormap = "turbo"

            out_layer = viewer.add_image(
                data["result"],
                colormap=out_colormap,
                name=f"pred_{image_id}_{model_name}",
                opacity=0.8,
            )

    @staticmethod
    @thread_worker
    def inference(
        device,
        model_dict,
        weights,
        images_filepaths,
        results_path,
        filetype,
        transforms,
        logging,
    ):
        """

        Args:
            device: cuda or cpu device to use for torch
            model_dict: the :py:attr:`~self.models_dict` dictionary to obtain the model name, class and instance
            weights: the loaded weights from the model
            images_filepaths: the paths to the images of the dataset
            results_path: the path to save the results
            filetype: the file extension to use when saving,
            transforms: a dict containing transforms to perform at various times.

        Yields:
            dict: contains :
                * "image_id" : index of the returned image

                * "original" : original volume used for inference

                * "result" : inference result

        """

        model = model_dict["instance"]
        model.to(device)

        images_dict = Inferer.create_inference_dict(images_filepaths)

        # TODO : better solution than loading first image always ?
        data = LoadImaged(keys=["image"])(images_dict[0])
        # print(data)
        check = data["image"].shape
        # print(check)
        # TODO remove
        # z_aniso = 5 / 1.5
        # if zoom is not None :
        #     pad = utils.get_padding_dim(check, anisotropy_factor=zoom)
        # else:
        logging("\nChecking dimensions...")
        pad = utils.get_padding_dim(check, logger=logging)
        # print(pad)

        load_transforms = Compose(
            [
                LoadImaged(keys=["image"]),
                # AddChanneld(keys=["image"]), #already done
                EnsureChannelFirstd(keys=["image"]),
                # Orientationd(keys=["image"], axcodes="PLI"),
                # anisotropic_transform,
                SpatialPadd(keys=["image"], spatial_size=pad),
                EnsureTyped(keys=["image"]),
            ]
        )

        if not transforms["thresh"][0]:
            post_process_transforms = EnsureType()
        else:
            t = transforms["thresh"][1]
            post_process_transforms = Compose(
                AsDiscrete(threshold=t), EnsureType()
            )

        # LabelFilter(applied_labels=[0]),

        logging("\nLoading dataset...")
        inference_ds = Dataset(
            data=images_dict, transform=load_transforms
        )
        inference_loader = DataLoader(
            inference_ds, batch_size=1, num_workers=1
        )
        logging("Done")
        # print(f"wh dir : {WEIGHTS_DIR}")
        # print(weights)
        logging("\nLoading weights...")
        model.load_state_dict(
            torch.load(os.path.join(WEIGHTS_DIR, weights), map_location=device)
        )
        logging("Done")

        model.eval()
        with torch.no_grad():
            for i, inf_data in enumerate(inference_loader):

                logging("-" * 10)
                logging(f"Inference started on image {i+1}...")

                inputs = inf_data["image"]
                # print(inputs.shape)
                inputs = inputs.to(device)

                model_output = lambda inputs: post_process_transforms(
                    model_dict["class"].get_output(model, inputs)
                )

                outputs = sliding_window_inference(
                    inputs,
                    roi_size=None,
                    sw_batch_size=1,
                    predictor=model_output,
                    device=device,
                )

                out = outputs.detach().cpu()

                if transforms["zoom"][0]:
                    zoom = transforms["zoom"][1]
                    anisotropic_transform = Zoom(
                        zoom=zoom,
                        keep_size=False,
                        padding_mode="empty",
                    )
                    out = anisotropic_transform(out[0])

                out = post_process_transforms(out)
                out = np.array(out).astype(np.float32)

                # batch_len = out.shape[1]
                # print("trying to check len")
                # print(batch_len)
                # if batch_len != 1 :
                #     sum  = np.sum(out, axis=1)
                #     print(sum.shape)
                #     out = sum
                #     print(out.shape)

                image_id = i + 1
                time = utils.get_date_time()
                # print(time)

                original_filename = os.path.basename(
                    images_filepaths[i]
                ).split(".")[0]

                # File output save name : original-name_model_date+time_number.filetype
                file_path = (
                    results_path
                    + "/"
                    + original_filename
                    + "_"
                    + model_dict["name"]
                    + f"_{time}_"
                    + f"pred_{image_id}"
                    + filetype
                )

                # print(filename)
                imwrite(file_path, out)

                logging(f"\nFile n°{image_id} saved as :")
                filename = os.path.split(file_path)[1]
                logging(filename)

                original = np.array(inf_data["image"]).astype(np.float32)

                # logging(f"Inference completed on image {i+1}")
                yield {
                    "image_id": i + 1,
                    "original": original,
                    "result": out,
                    "model_name": model_dict["name"],
                }
