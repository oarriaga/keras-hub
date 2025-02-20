import numpy as np
import pytest
from absl.testing import parameterized
from keras import ops
from keras.utils.bounding_boxes import convert_format

import keras_hub
from keras_hub.src.layers.modeling.non_max_supression import NonMaxSuppression
from keras_hub.src.models.yolo_v8.yolo_v8_presets import detector_presets
from keras_hub.src.tests.test_case import TestCase

test_backbone_presets = [
    "yolo_v8_xs_backbone_coco",
    "yolo_v8_s_backbone_coco",
    "yolo_v8_m_backbone_coco",
    "yolo_v8_l_backbone_coco",
    "yolo_v8_xl_backbone_coco",
]


def _create_bounding_box_dataset(bounding_box_format, image_size=512):
    # Just about the easiest dataset you can have, all classes are 0, all boxes
    # are exactly the same. [1, 1, 2, 2] are the coordinates in xyxy.
    xs = np.random.normal(size=(1, image_size, image_size, 3))
    xs = np.tile(xs, [5, 1, 1, 1])

    y_classes = np.zeros((5, 3), "float32")

    ys = np.array(
        [
            [0.1, 0.1, 0.23, 0.23],
            [0.67, 0.75, 0.23, 0.23],
            [0.25, 0.25, 0.23, 0.23],
        ],
        "float32",
    )
    ys = np.expand_dims(ys, axis=0)
    ys = np.tile(ys, [5, 1, 1])
    ys = ops.convert_to_numpy(
        convert_format(
            ys,
            source="rel_xywh",
            target=bounding_box_format,
            # images=xs,
            height=1,
            width=1,
            dtype="float32",
        )
    )
    return xs, {"boxes": ys, "classes": y_classes}


class YOLOV8DetectorTest(TestCase):
    @pytest.mark.large  # Fit is slow, so mark these large.
    def test_fit(self):
        bounding_box_format = "xywh"
        yolo = keras_hub.models.YOLOV8ImageObjectDetector(
            num_classes=2,
            fpn_depth=1,
            bounding_box_format=bounding_box_format,
            backbone=keras_hub.models.YOLOV8Backbone.from_preset(
                "yolo_v8_xs_backbone_coco"
            ),
        )

        yolo.compile(
            optimizer="adam",
            classification_loss="auto",
            box_loss="auto",
        )
        xs, ys = _create_bounding_box_dataset(bounding_box_format)

        yolo.fit(x=xs, y=ys, epochs=1)

    @pytest.mark.skip(
        reason="to_ragged has been deleted and requires tensorflow"
    )
    def test_fit_with_ragged_tensors(self):
        bounding_box_format = "xywh"
        yolo = keras_hub.models.YOLOV8ImageObjectDetector(
            num_classes=2,
            fpn_depth=1,
            bounding_box_format=bounding_box_format,
            backbone=keras_hub.models.YOLOV8Backbone.from_preset(
                "yolo_v8_xs_backbone_coco"
            ),
        )

        yolo.compile(
            optimizer="adam",
            classification_loss="auto",
            box_loss="auto",
        )
        xs, ys = _create_bounding_box_dataset(bounding_box_format)
        # ys = to_ragged(ys)
        yolo.fit(x=xs, y=ys, epochs=1)

    @pytest.mark.large  # Fit is slow, so mark these large.
    def test_fit_with_no_valid_gt_bbox(self):
        bounding_box_format = "xywh"
        yolo = keras_hub.models.YOLOV8ImageObjectDetector(
            num_classes=1,
            fpn_depth=1,
            bounding_box_format=bounding_box_format,
            backbone=keras_hub.models.YOLOV8Backbone.from_preset(
                "yolo_v8_xs_backbone_coco"
            ),
        )

        yolo.compile(
            optimizer="adam",
            classification_loss="auto",
            box_loss="auto",
        )
        xs, ys = _create_bounding_box_dataset(bounding_box_format)
        # Make all bounding_boxes invalid and filter out them
        ys["classes"] = -np.ones_like(ys["classes"])

        yolo.fit(x=xs, y=ys, epochs=1)

    def test_trainable_weight_count(self):
        yolo = keras_hub.models.YOLOV8ImageObjectDetector(
            num_classes=2,
            fpn_depth=1,
            bounding_box_format="xywh",
            backbone=keras_hub.models.YOLOV8Backbone.from_preset(
                "yolo_v8_s_backbone_coco"
            ),
        )

        self.assertEqual(len(yolo.trainable_weights), 195)

    def test_bad_loss(self):
        yolo = keras_hub.models.YOLOV8ImageObjectDetector(
            num_classes=2,
            fpn_depth=1,
            bounding_box_format="xywh",
            backbone=keras_hub.models.YOLOV8Backbone.from_preset(
                "yolo_v8_xs_backbone_coco"
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "Invalid box loss",
        ):
            yolo.compile(box_loss="bad_loss", classification_loss="auto")

        with self.assertRaisesRegex(
            ValueError,
            "Invalid classification loss",
        ):
            yolo.compile(box_loss="auto", classification_loss="bad_loss")

    @pytest.mark.large  # Saving is slow, so mark these large.
    def test_saved_model(self):
        init_kwargs = {
            "num_classes": 20,
            "bounding_box_format": "xywh",
            "fpn_depth": 1,
            "backbone": keras_hub.models.YOLOV8Backbone.from_preset(
                "yolo_v8_xs_backbone_coco"
            ),
        }

        xs, _ = _create_bounding_box_dataset("xywh")
        self.run_model_saving_test(
            cls=keras_hub.models.YOLOV8ImageObjectDetector,
            init_kwargs=init_kwargs,
            input_data=xs,
        )

    def test_update_prediction_decoder(self):
        yolo = keras_hub.models.YOLOV8ImageObjectDetector(
            num_classes=2,
            fpn_depth=1,
            bounding_box_format="xywh",
            backbone=keras_hub.models.YOLOV8Backbone.from_preset(
                "yolo_v8_s_backbone_coco"
            ),
            prediction_decoder=NonMaxSuppression(
                bounding_box_format="xywh",
                from_logits=False,
                confidence_threshold=0.0,
                iou_threshold=1.0,
            ),
        )

        image = np.ones((1, 512, 512, 3))

        outputs = yolo.predict(image)
        # We predicted at least 1 box with confidence_threshold 0
        self.assertGreater(outputs["boxes"].shape[0], 0)

        yolo.prediction_decoder = NonMaxSuppression(
            bounding_box_format="xywh",
            from_logits=False,
            confidence_threshold=1.0,
            iou_threshold=1.0,
        )

        outputs = yolo.predict(image)
        # We predicted no boxes with confidence threshold 1
        self.assertAllEqual(outputs["boxes"], -np.ones_like(outputs["boxes"]))
        self.assertAllEqual(
            outputs["confidence"], -np.ones_like(outputs["confidence"])
        )
        self.assertAllEqual(
            # outputs["classes"], -np.ones_like(outputs["classes"])
            outputs["labels"],
            -np.ones_like(outputs["labels"]),
        )

    def test_yolov8_basics(self):
        box_format = "xyxy"
        xs, ys = _create_bounding_box_dataset(box_format)
        backbone = keras_hub.models.YOLOV8Backbone.from_preset(
            "yolo_v8_m_backbone_coco"
        )
        scale = np.array(1.0 / 255).astype("float32")
        xs = xs.astype("float32")
        image_converter = keras_hub.layers.YOLOV8ImageConverter(scale=scale)
        preprocessor = keras_hub.models.YOLOV8ImageObjectDetectorPreprocessor(
            image_converter=image_converter
        )

        init_kwargs = {
            "backbone": backbone,
            "num_classes": 3,
            "bounding_box_format": box_format,
            "preprocessor": preprocessor,
        }
        self.run_task_test(
            cls=keras_hub.models.YOLOV8ImageObjectDetector,
            init_kwargs=init_kwargs,
            train_data=(xs, ys),
            batch_size=len(xs),
        )


@pytest.mark.large
class YOLOV8ImageObjectDetectorSmokeTest(TestCase):
    # @pytest.mark.skip(reason="Missing non YOLOV8 presets in KerasHub")
    @parameterized.named_parameters(
        *[(preset, preset) for preset in test_backbone_presets]
    )
    @pytest.mark.extra_large
    def test_backbone_preset(self, preset):
        backbone = keras_hub.models.YOLOV8Backbone.from_preset(preset)
        model = keras_hub.models.YOLOV8ImageObjectDetector(
            backbone=backbone,
            num_classes=20,
            bounding_box_format="xywh",
        )
        xs, _ = _create_bounding_box_dataset(bounding_box_format="xywh")
        output = model(xs)

        # 64 represents number of parameters in a box
        # 5376 is the number of anchors for a 512x512 image
        self.assertEqual(output["boxes"].shape, (xs.shape[0], 5376, 64))

    @parameterized.named_parameters(
        ("256x256", (256, 256)),
        ("512x512", (512, 512)),
    )
    def test_preset_with_forward_pass(self, image_size):
        model = keras_hub.models.YOLOV8ImageObjectDetector.from_preset(
            "yolo_v8_m_pascalvoc",
            bounding_box_format="xywh",
        )

        image = np.ones((1, image_size[0], image_size[1], 3))
        encoded_predictions = model(image / 255.0)

        if image_size == (512, 512):
            self.assertAllClose(
                ops.convert_to_numpy(encoded_predictions["boxes"][0, 0:5, 0]),
                [-0.8303556, 0.75213313, 1.809204, 1.6576759, 1.4134747],
            )
            self.assertAllClose(
                ops.convert_to_numpy(encoded_predictions["classes"][0, 0:5, 0]),
                [
                    7.6146556e-08,
                    8.0103280e-07,
                    9.7873999e-07,
                    2.2314548e-06,
                    2.5051115e-06,
                ],
            )
        if image_size == (256, 256):
            self.assertAllClose(
                ops.convert_to_numpy(encoded_predictions["boxes"][0, 0:5, 0]),
                [-0.6900742, 0.62832844, 1.6327355, 1.539787, 1.311696],
            )
            self.assertAllClose(
                ops.convert_to_numpy(encoded_predictions["classes"][0, 0:5, 0]),
                [
                    4.8766704e-08,
                    2.8596392e-07,
                    2.3858618e-07,
                    3.8180931e-07,
                    3.8900879e-07,
                ],
            )


@pytest.mark.extra_large
class YOLOV8DetectorPresetFullTest(TestCase):
    """
    Test the full enumeration of our presets.
    This every presets for YOLOV8Detector and is only run manually.
    Run with:
    `pytest keras_hub/models/object_detection/yolo_v8/
    yolo_v8_detector_test.py --run_extra_large`
    """

    def test_load_yolo_v8_detector(self):
        input_data = np.ones(shape=(2, 224, 224, 3))
        for preset in detector_presets:
            model = keras_hub.models.YOLOV8ImageObjectDetector.from_preset(
                preset, bounding_box_format="xywh"
            )
            model(input_data)
