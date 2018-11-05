from tensorflow.keras.utils import Sequence
from MultiViewUNet.utils import get_class_weights as gcw
from MultiViewUNet.logging import ScreenLogger
from MultiViewUNet.preprocessing import reshape_add_axis, one_hot_encode_y
import numpy as np


class IsotrophicLiveViewSequence(Sequence):
    def __init__(self, image_pair_loader, sample_dim, batch_size, n_classes,
                 real_space_span=None, noise_sd=0., force_all_fg="auto",
                 fg_batch_fraction=0.50, label_crop=None, logger=None,
                 is_validation=False, list_of_augmenters=None, sparse=True,
                 **kwargs):
        super().__init__()

        # Validation or training batch generator?
        self.is_validation = is_validation

        # Set logger or default print
        self.logger = logger or ScreenLogger()

        # Set views and attributes for plane sample generation
        self.sample_dim = sample_dim
        self.real_space_span = real_space_span
        self.noise_sd = noise_sd if not self.is_validation else 0.

        # Set data
        self.image_pair_loader = image_pair_loader
        self.images = image_pair_loader.images

        # Augmenter, applied to batch at creation time
        # Do not augment validation data
        self.list_of_augmenters = list_of_augmenters if not self.is_validation else None

        # Batch creation options
        self.batch_size = batch_size
        self.n_classes = n_classes
        self.sparse = sparse

        # Minimum fraction of slices in each batch with FG
        self.force_all_fg_switch = force_all_fg
        self.fg_batch_fraction = fg_batch_fraction

        # Store labels?
        self.store_y = False
        self.stored_y = []

        # Foreground label settings
        self.fg_classes = np.arange(1, self.n_classes)
        if self.fg_classes.shape[0] == 0:
            self.fg_classes = [1]

        # Set potential label label_crop
        self.label_crop = np.array([[0, 0], [0, 0]]) if label_crop is None else label_crop

    def __len__(self):
        raise NotImplemented

    def __getitem__(self, idx):
        raise NotImplemented

    def count(self):
        weights = [image.sample_weight for image in self.images]
        return np.unique(weights, return_counts=True)

    @property
    def n_samples(self):
        return len(self)

    @property
    def batch_size(self):
        return self._batch_size

    @batch_size.setter
    def batch_size(self, value):
        if value < 0:
            raise ValueError("Invalid batch size of %i" % value)
        self._batch_size = value

    @property
    def n_fg_slices(self):
        return int(np.ceil(self.batch_size * self.fg_batch_fraction))

    @property
    def force_all_fg(self):
        if isinstance(self.force_all_fg_switch, str) and \
                self.force_all_fg_switch.lower() == "auto":
            # If the batch size number is bigger than the total number of
            # FG classes, we force the batch to contain at least 1 voxel of
            # each class in one of the slices. If the total number of classes
            # exceeds the batch size, it may not be possible to have all
            # classes simultaneously. Can be overwritten with False/True.
            return self.batch_size > len(self.fg_classes)
        else:
            return self.force_all_fg_switch

    @property
    def store_y(self):
        return self._store_y

    @store_y.setter
    def store_y(self, value):
        self._store_y = value
        self.stored_y = []

    def get_class_weights(self, as_array=False):
        return gcw(self.image_pair_loader, as_array=as_array)

    def _crop_labels(self, batch_y):
        return batch_y[:, self.label_crop[0, 0]:-self.label_crop[0, 1],
                       :self.label_crop[1, 0]:-self.label_crop[1, 1]]

    def get_X_store_yw(self):
        pass

    def is_valid_im(self, im, bg_value):
        # Image slice should not be out of bounds (complete background)
        return np.any(~np.isclose(im, bg_value))

    def validate_lab_vec(self, lab, has_fg, cur_batch_size):
        new_mask = has_fg + np.isin(self.fg_classes, lab)
        if np.all(new_mask):
            return True, new_mask
        elif np.sum(new_mask == 0) < (self.batch_size - cur_batch_size):
            # No FG, but there are still enough random slices left to fill the
            # minimum requirement
            return True, new_mask
        else:
            # No FG, but there is not enough random slices left to fill the
            # minimum requirement. Discard the slice and sample again.
            return False, has_fg

    def validate_lab(self, lab, has_fg, cur_batch_size, debug=False):
        valid = np.any(np.isin(self.fg_classes, lab))

        if debug:
            print(valid, self.fg_classes)
            print(np.unique(lab, return_counts=True))
            print(self.batch_size, cur_batch_size, self.n_fg_slices, has_fg)

        if valid:
            return True, 1
        elif (self.n_fg_slices - has_fg) < (self.batch_size - cur_batch_size):
            # No FG, but there are still enough random slices left to fill the
            # minimum requirement
            return True, 0
        else:
            # No FG, but there is not enough random slices left to fill the
            # minimum requirement. Discard the slice and sample again.
            return False, 0

    def prepare_batches(self, batch_x, batch_y, batch_w):
        # Crop labels if necessary
        if self.label_crop.sum() != 0:
            batch_y = self._crop_labels(batch_y)

        # Reshape X (and one-hot encode y)
        batch_x = np.asarray(batch_x)

        if self.n_classes > 1 and not self.sparse:
            batch_y = one_hot_encode_y(batch_y, n_classes=self.n_classes)
        else:
            batch_y = np.asarray(batch_y)
            batch_y = batch_y.reshape(batch_y.shape + (1,))

        if self.store_y:
            self.stored_y.append(batch_y)

        return batch_x, batch_y, np.asarray(batch_w)

    def augment(self, batch_x, batch_y, batch_w, bg_values):
        # Apply further augmentation?
        if self.list_of_augmenters:
            for aug in self.list_of_augmenters:
                batch_x, batch_y, batch_w = aug(batch_x=batch_x,
                                                batch_y=batch_y,
                                                batch_w=batch_w,
                                                bg_values=bg_values)

        return batch_x, batch_y, batch_w

    def scale(self, batch_x, scalers):
        return [scaler.transform(im) for im, scaler in zip(batch_x, scalers)]
