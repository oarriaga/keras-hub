import math

import keras
from keras import ops

from keras_hub.src.bounding_box.converters import convert_format
from keras_hub.src.bounding_box.utils import as_relative
from keras_hub.src.bounding_box.utils import is_relative
from keras_hub.src.models.yolo_v8.mask_invalid_detections import (
    mask_invalid_detections,
)


class NonMaxSuppression(keras.layers.Layer):
    """A Keras layer that decodes predictions of an object detection model.

    Args:
        bounding_box_format: The format of bounding boxes of input dataset.
            Refer [Keras bounding box documentation](
            https://github.com/keras-team/keras/blob/master/keras/src/layers/
            preprocessing/image_preprocessing/bounding_boxes/formats.py).
            for more details on supported bounding box formats.
        from_logits: boolean, True means input score is logits, False means
            confidence.
        iou_threshold: a float value in the range `[0, 1]` representing the
            minimum IoU threshold for two boxes to be considered same for
            suppression. Defaults to 0.5.
        confidence_threshold: a float value in the range `[0, 1]`. All boxes
            with confidence below this value will be discarded, defaults to 0.5.
        max_detections: the maximum detections to consider after nms is applied.
            A large number may trigger significant memory overhead,
            defaults to 100.
    """

    def __init__(
        self,
        bounding_box_format,
        from_logits,
        iou_threshold=0.5,
        confidence_threshold=0.5,
        max_detections=100,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.bounding_box_format = bounding_box_format
        self.from_logits = from_logits
        self.iou_threshold = iou_threshold
        self.confidence_threshold = confidence_threshold
        self.max_detections = max_detections
        self.built = True

    def call(
        self, box_prediction, class_prediction, images=None, image_shape=None
    ):
        """Accepts images and raw predictions, and returns bounding box
        predictions.

        Args:
            box_prediction: Dense Tensor of shape `(batch, boxes, 4)` in the
                `bounding_box_format` specified in the constructor.
            class_prediction: Dense Tensor of shape `(batch, boxes,
                num_classes)`.
            images: (Optional) a batch of images of shape
                `(batch_size, height, width)`. Required when transforming
                from a relative format to a non-relative format.
            image_shape: (Optional) Tuple, list or tensor of shape (3)
                representing the `(height, width, num_channels)`. Required when
                transforming from a relative format to a non-relative format.
        """
        target_format = "yxyx"
        if is_relative(self.bounding_box_format):
            target_format = as_relative(target_format)

        box_prediction = convert_format(
            box_prediction,
            source=self.bounding_box_format,
            target=target_format,
            images=images,
            image_shape=image_shape,
        )
        if self.from_logits:
            class_prediction = ops.sigmoid(class_prediction)

        confidence_prediction = ops.max(class_prediction, axis=-1)

        idx, valid_det = non_max_suppression(
            box_prediction,
            confidence_prediction,
            max_output_size=self.max_detections,
            iou_threshold=self.iou_threshold,
            score_threshold=self.confidence_threshold,
        )

        box_prediction = ops.take_along_axis(
            box_prediction, ops.expand_dims(idx, axis=-1), axis=1
        )
        box_prediction = ops.reshape(
            box_prediction, (-1, self.max_detections, 4)
        )
        confidence_prediction = ops.take_along_axis(
            confidence_prediction, idx, axis=1
        )
        class_prediction = ops.take_along_axis(
            class_prediction, ops.expand_dims(idx, axis=-1), axis=1
        )

        box_prediction = convert_format(
            box_prediction,
            source=target_format,
            target=self.bounding_box_format,
            images=images,
            image_shape=image_shape,
        )
        bounding_boxes = {
            "idx": idx,
            "boxes": box_prediction,
            "confidence": confidence_prediction,
            "classes": ops.argmax(class_prediction, axis=-1),
            "num_detections": valid_det,
        }
        return mask_invalid_detections(bounding_boxes, output_ragged=False)

    def build(self, box_prediction_shape, class_prediction_shape):
        return

    def get_config(self):
        config = {
            "bounding_box_format": self.bounding_box_format,
            "from_logits": self.from_logits,
            "iou_threshold": self.iou_threshold,
            "confidence_threshold": self.confidence_threshold,
            "max_detections": self.max_detections,
        }
        base_config = super().get_config()
        return dict(list(base_config.items()) + list(config.items()))


def _sort_scores_and_boxes(scores, boxes):
    """Sort boxes based their score from highest to lowest.

    Args:
        scores: a tensor with a shape of `(batch_size, num_boxes)` representing
            the scores of boxes.
        boxes: a tensor with a shape of `(batch_size, num_boxes, 4)`
            representing the boxes.

    Returns:
        sorted_scores: a tensor with a shape of `(batch_size, num_boxes)`
            representing the sorted scores.
        sorted_boxes: a tensor representing the sorted boxes.
        sorted_scores_indices: a tensor with a shape of
            `(batch_size, num_boxes)`
            representing the index of the scores in a sorted descending order.
    """
    sorted_scores_indices = ops.flip(
        ops.cast(ops.argsort(scores, axis=1), "int32"), axis=1
    )
    sorted_scores = ops.take_along_axis(
        scores,
        sorted_scores_indices,
        axis=1,
    )
    sorted_boxes = ops.take_along_axis(
        boxes,
        ops.expand_dims(sorted_scores_indices, axis=-1),
        axis=1,
    )

    return sorted_scores, sorted_boxes, sorted_scores_indices


def non_max_suppression(
    boxes,
    scores,
    max_output_size,
    iou_threshold=0.5,
    score_threshold=0.0,
    tile_size=512,
):
    # Box format must be yxyx
    """Non-maximum suppression.

    Port from [tensorflow NMS implementation](https://github.com/tensorflow/
    tensorflow/blob/v2.12.0/tensorflow/python/ops/
    image_ops_impl.py#L5368-L5458)

    Args:
        boxes: a tensor with a shape of `(batch_size, num_boxes, 4)`.
            Dimensions except the last two are batch dimensions.
            The last dimension represents box coordinates in yxyx format.
        scores: a tensor with a shape of `(batch_size, num_boxes)`.
        max_output_size: a scalar integer tensor representing the maximum number
            of boxes to be selected by non max suppression.
        iou_threshold: a float representing the threshold for deciding whether
            boxes overlap too much with respect to IoU
            `(intersection over union)`.
        score_threshold: a float representing the threshold for box scores.
            Boxes with a score that is not larger than this threshold will be
            suppressed.
        tile_size: an integer representing the number of boxes in a tile, i.e.,
            the maximum number of boxes per image that can be used to suppress
            other boxes in parallel; larger tile_size means larger parallelism
            and potentially more redundant work.

    Returns:
        selected_box_args: a tensor with a shape of `(..., num_boxes)`
            representing the indices selected by non-max suppression.
            The leading dimensions are the batch dimensions of the input boxes.
            All numbers are within `(0, num_boxes)`. For each image
            (i.e., `selected_box_args[i]`), only the first `num_valid[i]`
            indices (i.e., `selected_box_args[i][:num_valid[i]]`) are valid.
        num_valid: a tensor of rank 0 or higher representing the number of
            valid indices in selected_box_args. Its dimensions are the batch
            dimensions of the input boxes.
    """
    batch_dims = ops.shape(boxes)[:-2]
    num_boxes = boxes.shape[-2]
    boxes = ops.reshape(boxes, [-1, num_boxes, 4])
    scores = ops.reshape(scores, [-1, num_boxes])
    batch_size = boxes.shape[0]
    if score_threshold != float("-inf"):
        score_mask = ops.cast(scores > score_threshold, scores.dtype)
        scores *= score_mask
        box_mask = ops.expand_dims(ops.cast(score_mask, boxes.dtype), 2)
        boxes *= box_mask

    scores, boxes, sorted_indices = _sort_scores_and_boxes(scores, boxes)

    pad = (
        math.ceil(max(num_boxes, max_output_size) / tile_size) * tile_size
        - num_boxes
    )
    boxes = ops.pad(ops.cast(boxes, "float32"), [[0, 0], [0, pad], [0, 0]])
    scores = ops.pad(ops.cast(scores, "float32"), [[0, 0], [0, pad]])
    num_boxes_after_padding = num_boxes + pad
    num_iterations = num_boxes_after_padding // tile_size

    def _loop_cond(unused_boxes, unused_threshold, output_size, tile_arg):
        return ops.logical_and(
            ops.min(output_size) < ops.cast(max_output_size, "int32"),
            ops.cast(tile_arg, "int32") < num_iterations,
        )

    def suppression_loop_body(boxes, iou_threshold, output_size, tile_arg):
        return _suppression_loop_body(
            boxes, iou_threshold, output_size, tile_arg, tile_size
        )

    selected_boxes, _, output_size, _ = ops.while_loop(
        _loop_cond,
        suppression_loop_body,
        [
            boxes,
            iou_threshold,
            ops.zeros([batch_size], "int32"),
            ops.array(0),
        ],
    )
    num_valid = ops.minimum(output_size, max_output_size)
    selected_box_args = num_boxes_after_padding - ops.cast(
        ops.top_k(
            ops.cast(ops.any(selected_boxes > 0, [2]), "int32")
            * ops.cast(
                ops.expand_dims(ops.arange(num_boxes_after_padding, 0, -1), 0),
                "int32",
            ),
            max_output_size,
        )[0],
        "int32",
    )
    selected_box_args = ops.minimum(selected_box_args, num_boxes - 1)

    index_offsets = ops.cast(ops.arange(batch_size) * num_boxes, "int32")
    take_along_axis_idx = ops.reshape(
        selected_box_args + ops.expand_dims(index_offsets, 1), [-1]
    )

    selected_box_args = ops.take_along_axis(
        ops.reshape(sorted_indices, [-1]), take_along_axis_idx
    )

    selected_box_args = ops.reshape(selected_box_args, [batch_size, -1])

    invalid_index = ops.zeros([batch_size, max_output_size], dtype="int32")
    idx_index = ops.cast(
        ops.expand_dims(ops.arange(max_output_size), 0), "int32"
    )
    num_valid_expanded = ops.expand_dims(num_valid, 1)
    selected_box_args = ops.where(
        idx_index < num_valid_expanded, selected_box_args, invalid_index
    )

    num_valid = ops.reshape(num_valid, batch_dims)
    return selected_box_args, num_valid


def _bbox_overlap(boxes_a, boxes_b):
    """Calculates the overlap (iou - intersection over union) between boxes_a
    and boxes_b.

    Args:
        boxes_a: a tensor with a shape of `(batch_size, N, 4)`. N is the number
            of boxes per image. The last dimension is the pixel coordinates in
            `[ymin, xmin, ymax, xmax]` form.
        boxes_b: a tensor with a shape of `(batch_size, M, 4)`. M is the number
            of boxes. The last dimension is the pixel coordinates in
            `[ymin, xmin, ymax, xmax]` form.

    Returns:
        intersection_over_union: a tensor with as a shape of
            `(batch_size, N, M)`, representing the ratio of intersection area
            over union area (IoU) between two boxes.
    """
    if len(boxes_a.shape) == 4:
        boxes_a = ops.squeeze(boxes_a, axis=0)
    a_y_min, a_x_min, a_y_max, a_x_max = ops.split(boxes_a, 4, axis=2)
    b_y_min, b_x_min, b_y_max, b_x_max = ops.split(boxes_b, 4, axis=2)

    # Calculates the intersection area.
    i_xmin = ops.maximum(a_x_min, ops.transpose(b_x_min, [0, 2, 1]))
    i_xmax = ops.minimum(a_x_max, ops.transpose(b_x_max, [0, 2, 1]))
    i_ymin = ops.maximum(a_y_min, ops.transpose(b_y_min, [0, 2, 1]))
    i_ymax = ops.minimum(a_y_max, ops.transpose(b_y_max, [0, 2, 1]))
    i_area = ops.maximum((i_xmax - i_xmin), 0) * ops.maximum(
        (i_ymax - i_ymin), 0
    )

    # Calculates the union area.
    a_area = (a_y_max - a_y_min) * (a_x_max - a_x_min)
    b_area = (b_y_max - b_y_min) * (b_x_max - b_x_min)

    # Adds a small epsilon to avoid divide-by-zero.
    u_area = a_area + ops.transpose(b_area, [0, 2, 1]) - i_area + 1e-8

    intersection_over_union = i_area / u_area

    return intersection_over_union


def _self_suppression(iou, _, iou_sum, iou_threshold):
    """Suppress boxes in the same tile.

    Compute boxes that cannot be suppressed by others (i.e.,
    can_suppress_others), and then use them to suppress boxes in the same tile.

    Args:
        iou: a tensor of shape `(batch_size, num_boxes_with_padding)`
            representing intersection over union.
        iou_sum: Tensor of shape `(batch)` representing the sum of all the boxes
            intersection over unions.
        iou_threshold: a float representing the threshold for deciding whether
            boxes overlap too much with respect to IoU
            (intersection over union).

    Returns:
        iou_suppressed: a tensor of shape
            `(batch_size, num_boxes_with_padding)`.
        iou_diff: a scalar tensor representing whether any box is suppressed in
            this step.
        iou_sum_new: a scalar tensor of shape [batch_size] that represents
            the iou sum after suppression.
        iou_threshold: a scalar tensor.
    """
    batch_size = ops.shape(iou)[0]
    can_suppress_others = ops.cast(
        ops.reshape(ops.max(iou, 1) < iou_threshold, [batch_size, -1, 1]),
        iou.dtype,
    )
    iou_after_suppression = (
        ops.reshape(
            ops.cast(
                ops.max(can_suppress_others * iou, 1) < iou_threshold, iou.dtype
            ),
            [batch_size, -1, 1],
        )
        * iou
    )
    iou_sum_new = ops.sum(iou_after_suppression, [1, 2])
    return [
        iou_after_suppression,
        ops.any(iou_sum - iou_sum_new > iou_threshold),
        iou_sum_new,
        iou_threshold,
    ]


def _cross_suppression(boxes, box_slice, iou_threshold, tile_arg, tile_size):
    """Suppress boxes between different tiles.

    Args:
        boxes: a tensor with a shape of `(batch_size, anchors, 4)`.
        box_slice: tensor of shape `(batch_size, tile_size, 4)` containing the
            boxes in the tile index tile_arg.
        iou_threshold: a float representing the threshold for deciding whether
            boxes overlap too much with respect to IoU
            (intersection over union).
        tile_arg: a scalar tensor representing the tile index of the tile
            that is used to suppress box_slice
        tile_size: an integer representing the number of boxes in a tile

    Returns:
        boxes: unchanged boxes as input
        box_slice_after_suppression: box_slice after suppression
            iou_threshold: unchanged
    """
    slice_index = ops.expand_dims(
        ops.expand_dims(
            ops.cast(
                ops.linspace(
                    tile_arg * tile_size,
                    (tile_arg + 1) * tile_size - 1,
                    tile_size,
                ),
                "int32",
            ),
            axis=0,
        ),
        axis=-1,
    )
    new_slice = ops.expand_dims(
        ops.take_along_axis(boxes, slice_index, axis=1), 0
    )
    iou = _bbox_overlap(new_slice, box_slice)
    box_slice_after_suppression = (
        ops.expand_dims(
            ops.cast(ops.all(iou < iou_threshold, [1]), box_slice.dtype), 2
        )
        * box_slice
    )
    return boxes, box_slice_after_suppression, iou_threshold, tile_arg + 1


def _suppression_loop_body(
    boxes, iou_threshold, output_size, tile_arg, tile_size
):
    """Process boxes in range `[tile_arg*tile_size, (tile_arg+1)*tile_size]`.

    Args:
        boxes: a tensor with a shape of `(batch_size, anchors, 4)`.
        iou_threshold: a float representing the threshold for deciding whether
            boxes overlap too much with respect to IOU.
        output_size: an int32 tensor of size `(batch_size)`. Representing the
            number of selected boxes for each batch.
        tile_arg: integer representing the induction tile variable.
        tile_size: an integer representing the number of boxes in a tile

    Returns:
        boxes: updated boxes.
        iou_threshold: pass down iou_threshold to the next iteration.
        output_size: the updated output_size.
        tile_arg: the updated induction variable.
    """
    num_tiles = boxes.shape[1] // tile_size
    batch_size = boxes.shape[0]

    def cross_suppression_func(boxes, box_slice, iou_threshold, inner_idx):
        return _cross_suppression(
            boxes, box_slice, iou_threshold, inner_idx, tile_size
        )

    # Iterates over tiles that can possibly suppress the current tile.
    slice_index = ops.expand_dims(
        ops.expand_dims(
            ops.cast(
                ops.linspace(
                    tile_arg * tile_size,
                    (tile_arg + 1) * tile_size - 1,
                    tile_size,
                ),
                "int32",
            ),
            axis=0,
        ),
        axis=-1,
    )
    box_slice = ops.take_along_axis(boxes, slice_index, axis=1)
    _, box_slice, _, _ = ops.while_loop(
        lambda _boxes, _box_slice, _threshold, inner_idx: inner_idx < tile_arg,
        cross_suppression_func,
        [boxes, box_slice, iou_threshold, ops.array(0)],
    )

    # Iterates over the current tile to compute self-suppression.
    iou = _bbox_overlap(box_slice, box_slice)
    mask = ops.expand_dims(
        ops.reshape(ops.arange(tile_size), [1, -1])
        > ops.reshape(ops.arange(tile_size), [-1, 1]),
        0,
    )
    iou *= ops.cast(ops.logical_and(mask, iou >= iou_threshold), iou.dtype)
    suppressed_iou, _, _, _ = ops.while_loop(
        lambda _iou, loop_condition, _iou_sum, _: loop_condition,
        _self_suppression,
        [iou, ops.array(True), ops.sum(iou, [1, 2]), iou_threshold],
    )
    suppressed_box = ops.sum(suppressed_iou, 1) > 0
    box_slice *= ops.expand_dims(
        1.0 - ops.cast(suppressed_box, box_slice.dtype), 2
    )

    # Uses box_slice to update the input boxes.
    mask = ops.reshape(
        ops.cast(ops.equal(ops.arange(num_tiles), tile_arg), boxes.dtype),
        [1, -1, 1, 1],
    )
    boxes = ops.tile(
        ops.expand_dims(box_slice, 1), [1, num_tiles, 1, 1]
    ) * mask + ops.reshape(boxes, [batch_size, num_tiles, tile_size, 4]) * (
        1 - mask
    )
    boxes = ops.reshape(boxes, [batch_size, -1, 4])

    # Updates output_size.
    output_size += ops.cast(ops.sum(ops.any(box_slice > 0, [2]), [1]), "int32")

    return boxes, iou_threshold, output_size, tile_arg + 1
