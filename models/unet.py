"""
Mathias Perslev
MSc Bioinformatics

University of Copenhagen
November 2017
"""

from MultiViewUNet.logging import ScreenLogger
from MultiViewUNet.utils.conv_arithmetics import compute_receptive_fields

from tensorflow.keras.models import Model
from tensorflow.keras import regularizers
from tensorflow.keras.layers import Input, BatchNormalization, Cropping2D, \
                                    Concatenate, Conv2D, MaxPooling2D, \
                                    UpSampling2D
import numpy as np


class UNet(Model):
    """
    2D UNet implementation with batch normalization and complexity factor adj.

    See original paper at http://arxiv.org/abs/1505.04597
    """
    def __init__(self, n_classes, img_rows=None, img_cols=None, dim=None,
                 n_channels=1, depth=4, out_activation="softmax",
                 activation="relu", kernel_size=3, padding="same",
                 complexity_factor=1, l2_reg=None, logger=None, **kwargs):
        """
        n_classes (int):
            The number of classes to model, gives the number of filters in the
            final 1x1 conv layer.
        img_rows, img_cols (int, int):
            Image dimensions. Note that depending on image dims cropping may
            be necessary. To avoid this, use image dimensions DxD for which
            D * (1/2)^n is an integer, where n is the number of (2x2)
            max-pooling layers; in this implementation 4.
            For n=4, D \in {..., 192, 208, 224, 240, 256, ...} etc.
        dim (int):
            img_rows and img_cols will both be set to 'dim'
        n_channels (int):
            Number of channels in the input image.
        depth (int):
            Number of conv blocks in encoding layer (number of 2x2 max pools)
            Note: each block doubles the filter count while halving the spatial
            dimensions of the features.
        out_activation (string):
            Activation function of output 1x1 conv layer. Usually one of
            'softmax', 'sigmoid' or 'linear'.
        activation (string):
            Activation function for convolution layers
        kernel_size (int):
            Kernel size for convolution layers
        padding (string):
            Padding type ('same' or 'valid')
        complexity_factor (int/float):
            Use int(N * sqrt(complexity_factor)) number of filters in each
            2D convolution layer instead of default N.
        l2_reg (float in [0, 1])
            L2 regularization on Conv2D weights
        logger (MultiViewUNet.logging.Logger | ScreenLogger):
            MutliViewUNet.Logger object, logging to files or screen.
        """
        if not ((img_rows and img_cols) or dim):
            raise ValueError("Must specify either img_rows and img_col or dim")
        if dim:
            img_rows, img_cols = dim, dim

        # Set logger or standard print wrapper
        self.logger = logger or ScreenLogger()

        # Set various attributes
        self.img_shape = (img_rows, img_cols, n_channels)
        self.n_classes = n_classes
        self.cf = np.sqrt(complexity_factor)
        self.kernel_size = kernel_size
        self.activation = activation
        self.out_activation = out_activation
        self.l2_reg = l2_reg
        self.padding = padding
        self.depth = depth

        # Shows the number of pixels cropped of the input image to the output
        self.label_crop = np.array([[0, 0], [0, 0]])

        # Build model and init base keras Model class
        super().__init__(*self.init_model())

        # Compute receptive field
        names = [x.__class__.__name__ for x in self.layers]
        index = names.index("UpSampling2D")
        self.receptive_field = compute_receptive_fields(self.layers[:index])[-1][-1]

        # Log the model definition
        self.log()

    def init_model(self):
        """
        Build the UNet model with the specified input image shape.
        """
        inputs = Input(shape=self.img_shape)

        # Apply regularization if not None or 0
        kr = regularizers.l2(self.l2_reg) if self.l2_reg else None

        """
        Encoding path
        """
        filters = 64
        in_ = inputs
        residual_connections = []
        for i in range(self.depth):
            conv = Conv2D(int(filters*self.cf), self.kernel_size,
                          activation=self.activation, padding=self.padding,
                          kernel_regularizer=kr)(in_)
            conv = Conv2D(int(filters * self.cf), self.kernel_size,
                          activation=self.activation, padding=self.padding,
                          kernel_regularizer=kr)(conv)
            bn = BatchNormalization()(conv)
            in_ = MaxPooling2D(pool_size=(2, 2))(bn)

            # Update filter count and add bn layer to list for residual conn.
            filters *= 2
            residual_connections.append(bn)

        """
        Bottom (no max-pool)
        """
        conv = Conv2D(int(filters * self.cf), self.kernel_size,
                      activation=self.activation, padding=self.padding,
                      kernel_regularizer=kr)(in_)
        conv = Conv2D(int(filters * self.cf), self.kernel_size,
                      activation=self.activation, padding=self.padding,
                      kernel_regularizer=kr)(conv)
        bn = BatchNormalization()(conv)

        """
        Up-sampling
        """
        residual_connections = residual_connections[::-1]
        for i in range(self.depth):
            # Reduce filter count
            filters /= 2

            # Up-sampling block
            # Note: 2x2 filters used for backward comp, but you probably
            # want to use 3x3 here instead.
            up = UpSampling2D(size=(2, 2))(bn)
            conv = Conv2D(int(filters * self.cf), 2, activation=self.activation,
                          padding=self.padding, kernel_regularizer=kr)(up)
            bn = BatchNormalization()(conv)

            # Crop and concatenate
            cropped_res = self.crop_nodes_to_match(residual_connections[i], bn)
            merge = Concatenate(axis=-1)([cropped_res, bn])

            conv = Conv2D(int(filters * self.cf), self.kernel_size,
                          activation=self.activation, padding=self.padding,
                          kernel_regularizer=kr)(merge)
            conv = Conv2D(int(filters * self.cf), self.kernel_size,
                          activation=self.activation, padding=self.padding,
                          kernel_regularizer=kr)(conv)
            bn = BatchNormalization()(conv)

        """
        Output modeling layer
        """
        out = Conv2D(self.n_classes, 1, activation=self.out_activation)(bn)

        return [inputs], [out]

    def crop_nodes_to_match(self, node1, node2):
        """
        If necessary, applies Cropping2D layer to node1 to match shape of node2
        """
        s1 = np.array(node1.get_shape().as_list())[1:-1]
        s2 = np.array(node2.get_shape().as_list())[1:-1]

        if np.any(s1 != s2):
            c = (s1 - s2).astype(np.int)
            cr = np.array([c//2, c//2]).T
            cr[:, 1] += c % 2
            cropped_node1 = Cropping2D(cr)(node1)
            self.label_crop += cr
        else:
            cropped_node1 = node1

        return cropped_node1

    def log(self):
        self.logger("UNet Model Summary\n------------------")
        self.logger("Image rows:        %i" % self.img_shape[0])
        self.logger("Image cols:        %i" % self.img_shape[1])
        self.logger("Image channels:    %i" % self.img_shape[2])
        self.logger("N classes:         %i" % self.n_classes)
        self.logger("CF factor:         %.3f" % self.cf**2)
        self.logger("Depth:             %i" % self.depth)
        self.logger("l2 reg:            %s" % self.l2_reg)
        self.logger("Padding:           %s" % self.padding)
        self.logger("Conv activation:   %s" % self.activation)
        self.logger("Out activation:    %s" % self.out_activation)
        self.logger("Receptive field:   %s" % self.receptive_field)
        self.logger("N params:          %i" % self.count_params())
        self.logger("Output:            %s" % self.output)
        self.logger("Crop:              %s" % (self.label_crop if np.sum(self.label_crop) != 0 else "None"))
