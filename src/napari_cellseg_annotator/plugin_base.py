import os

import napari
from qtpy.QtWidgets import QLineEdit
from qtpy.QtWidgets import QSizePolicy
from qtpy.QtWidgets import QWidget

from napari_cellseg_annotator import interface as ui


class BasePlugin(QWidget):
    """A plugin base that pre-defines a lot of common IO utility, for inheritance in other widgets"""

    def __init__(self, viewer: "napari.viewer.Viewer"):
        """Creates a Base plugin with several buttons pre-defined but not added to a layout :

        * Open file prompt to select images directory

        * Open file prompt to select labels directory

        * A checkbox to choose whether to load a folder of images or a single 3D file
          If toggled, shows a filetype option to select the extension

        * A close button that closes the widget

        * A dropdown menu with a choice of png or tif filetypes
        """

        super().__init__()

        # self.master = parent
        self._viewer = viewer
        """napari.viewer.Viewer: viewer in which the widget is displayed"""

        self.image_path = ""
        """str: path to image folder"""

        self.label_path = ""
        """str: path to label folder"""

        self.filetype = ""
        """str: filetype, .tif or .png"""
        self.as_folder = False
        """bool: Whether to load a single file or a folder as a stack"""

        self._default_path = [self.image_path, self.label_path]

        self.btn_image = ui.make_button("Open", self.show_dialog_images, self)
        """Button to load image folder"""
        self.lbl_image = QLineEdit("Images directory", self)
        self.lbl_image.setReadOnly(True)

        self.lbl_label = QLineEdit("Labels directory", self)
        """Button to load label folder"""
        self.lbl_label.setReadOnly(True)
        self.btn_label = ui.make_button("Open", self.show_dialog_labels, self)

        self.filetype_choice = ui.make_combobox([".png", ".tif"])

        self.file_handling_box = ui.make_checkbox(
            "Load as folder ?", self.show_filetype_choice
        )
        """Checkbox to choose single file or directory loader handling"""

        self.file_handling_box.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Fixed
        )

        self.btn_close = ui.make_button("Close", self.close, self)

        # self.lbl_ft = QLabel("Filetype :", self)
        # self.lbl_ft2 = QLabel("(Folders of .png or single .tif files)", self)

    def build(self):
        """Method to be defined by children classes"""
        raise NotImplementedError

    def show_filetype_choice(self):
        """Method to show/hide the filetype choice when "loading as folder" is (de)selected"""
        show = self.file_handling_box.isChecked()
        if show is not None:
            self.filetype_choice.setVisible(show)
            # self.lbl_ft.setVisible(show)

    def show_file_dialog(self):
        """Open file dialog and process path depending on single file/folder loading behaviour"""
        f_or_dir_name = ui.open_file_dialog(
            self, self._default_path, self.file_handling_box.isChecked()
        )
        if not self.file_handling_box.isChecked():
            f_or_dir_name = str(f_or_dir_name[0])
            self.filetype = os.path.splitext(f_or_dir_name)[1]

        print(f_or_dir_name)

        return f_or_dir_name

    def show_dialog_images(self):
        """Show file dialog and set image path"""
        f_name = self.show_file_dialog()
        if type(f_name) is str and f_name != "":
            self.image_path = f_name
            self.lbl_image.setText(self.image_path)
            self.update_default()

    def show_dialog_labels(self):
        """Show file dialog and set label path"""
        f_name = self.show_file_dialog()
        if type(f_name) is str and f_name != "":
            self.label_path = f_name
            self.lbl_label.setText(self.label_path)
            self.update_default()

    def update_default(self):
        self._default_path = [self.image_path, self.label_path]

    def close(self):
        """Removes the widget from the napari window.
        Can be re-implemented in children classes if needed"""
        self._viewer.window.remove_dock_widget(self)