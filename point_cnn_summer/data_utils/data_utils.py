from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import random

import h5py
import plyfile
import numpy as np
from matplotlib import cm

def save_ply(points, filename, colors=None, normals=None):
    vertex = np.array([tuple(p) for p in points], dtype=[('x', 'f4'), ('y', 'f4'), ('z', 'f4')])
    n = len(vertex)
    desc = vertex.dtype.descr

    if normals is not None:
        vertex_normal = np.array([tuple(n) for n in normals], dtype=[('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4')])
        assert len(vertex_normal) == n
        desc = desc + vertex_normal.dtype.descr

    if colors is not None:
        vertex_color = np.array([tuple(c * 255) for c in colors],
                                dtype=[('red', 'u1'), ('green', 'u1'), ('blue', 'u1')])
        assert len(vertex_color) == n
        desc = desc + vertex_color.dtype.descr

    vertex_all = np.empty(n, dtype=desc)

    for prop in vertex.dtype.names:
        vertex_all[prop] = vertex[prop]

    if normals is not None:
        for prop in vertex_normal.dtype.names:
            vertex_all[prop] = vertex_normal[prop]

    if colors is not None:
        for prop in vertex_color.dtype.names:
            vertex_all[prop] = vertex_color[prop]

    ply = plyfile.PlyData([plyfile.PlyElement.describe(vertex_all, 'vertex')], text=False)
    if not os.path.exists(os.path.dirname(filename)):
        os.makedirs(os.path.dirname(filename))
    ply.write(filename)


def save_ply_property(points, property, property_max, filename, cmap_name='tab20'):
    point_num = points.shape[0]
    colors = np.full(points.shape, 0.5)
    cmap = cm.get_cmap(cmap_name)
    for point_idx in range(point_num):
        if property[point_idx] == 0:
            colors[point_idx] = np.array([0, 0, 0])
        else:
            colors[point_idx] = cmap(property[point_idx] / property_max)[:3]
    save_ply(points, filename, colors)


def save_ply_batch(points_batch, file_path, points_num=None):
    batch_size = points_batch.shape[0]
    if type(file_path) != list:
        basename = os.path.splitext(file_path)[0]
        ext = '.ply'
    for batch_idx in range(batch_size):
        point_num = points_batch.shape[1] if points_num is None else points_num[batch_idx]
        if type(file_path) == list:
            save_ply(points_batch[batch_idx][:point_num], file_path[batch_idx])
        else:
            save_ply(points_batch[batch_idx][:point_num], '%s_%04d%s' % (basename, batch_idx, ext))


def save_ply_color_batch(points_batch, colors_batch, file_path, points_num=None):
    batch_size = points_batch.shape[0]
    if type(file_path) != list:
        basename = os.path.splitext(file_path)[0]
        ext = '.ply'
    for batch_idx in range(batch_size):
        point_num = points_batch.shape[1] if points_num is None else points_num[batch_idx]
        if type(file_path) == list:
            save_ply(points_batch[batch_idx][:point_num], file_path[batch_idx], colors_batch[batch_idx][:point_num])
        else:
            save_ply(points_batch[batch_idx][:point_num], '%s_%04d%s' % (basename, batch_idx, ext),
                     colors_batch[batch_idx][:point_num])


def save_ply_property_batch(points_batch, property_batch, file_path, points_num=None, property_max=None,
                            cmap_name='tab20'):
    batch_size = points_batch.shape[0]
    if type(file_path) != list:
        basename = os.path.splitext(file_path)[0]
        ext = '.ply'
    property_max = np.max(property_batch) if property_max is None else property_max
    for batch_idx in range(batch_size):
        point_num = points_batch.shape[1] if points_num is None else points_num[batch_idx]
        if type(file_path) == list:
            save_ply_property(points_batch[batch_idx][:point_num], property_batch[batch_idx][:point_num],
                              property_max, file_path[batch_idx], cmap_name)
        else:
            save_ply_property(points_batch[batch_idx][:point_num], property_batch[batch_idx][:point_num],
                              property_max, '%s_%04d%s' % (basename, batch_idx, ext), cmap_name)


def save_ply_point_with_normal(data_sample, folder):
    for idx, sample in enumerate(data_sample):
        filename_pts = os.path.join(folder, '{:08d}.ply'.format(idx))
        save_ply(sample[..., :3], filename_pts, normals=sample[..., 3:])


def grouped_shuffle(inputs):
    for idx in range(len(inputs) - 1):
        assert (len(inputs[idx]) == len(inputs[idx + 1]))

    shuffle_indices = np.arange(inputs[0].shape[0])
    np.random.shuffle(shuffle_indices)
    outputs = []
    for idx in range(len(inputs)):
        outputs.append(inputs[idx][shuffle_indices, ...])
    return outputs


def index_shuffle(index_length):
    shuffle_indices = np.arange(index_length.shape[0])
    np.random.shuffle(shuffle_indices)
    return index_length[shuffle_indices, ...]


def load_cls(filelist):
    points = []
    labels = []

    folder = os.path.dirname(filelist)
    for line in open(filelist):
        filename = os.path.basename(line.rstrip())
        data = h5py.File(os.path.join(folder, filename))
        if 'normal' in data:
            points.append(np.concatenate([data['data'][...], data['normal'][...]], axis=-1).astype(np.float32))
        else:
            points.append(data['data'][...].astype(np.float32))
        labels.append(np.squeeze(data['label'][:]).astype(np.int64))
    return (np.concatenate(points, axis=0),
            np.concatenate(labels, axis=0))


def load_cls_train_val(filelist, filelist_val):
    data_train, label_train = grouped_shuffle(load_cls(filelist))
    data_val, label_val = load_cls(filelist_val)
    return data_train, label_train, data_val, label_val


def is_h5_list(filelist):
    return all([line.strip()[-3:] == '.h5' for line in open(filelist)])


def load_seg_list(filelist):
    folder = os.path.dirname(filelist)
    return [os.path.join(folder, line.strip()) for line in open(filelist)]


def load_seg(filelist):
    points = []
    intensity_features = []
    point_nums = []
    labels_seg = []

    folder = os.path.dirname(filelist)
    for line in open(filelist):
        filename = os.path.basename(line.rstrip())
        data = h5py.File(os.path.join(folder, filename))
        points.append(data['data'][...].astype(np.float32))
        intensity_features.append(data['intensity'][...].astype(np.float32))
        point_nums.append(data['data_num'][...].astype(np.int32))
        labels_seg.append(data['label_seg'][...].astype(np.int32))
    return (np.concatenate(points, axis=0),
            np.concatenate(intensity_features, axis=0),
            np.concatenate(point_nums, axis=0),
            np.concatenate(labels_seg, axis=0))


def load_data(filelist):
    points = []
    intensity_features = []
    point_nums = []

    folder = os.path.dirname(filelist)
    for line in open(filelist):
        filename = os.path.basename(line.rstrip())
        data = h5py.File(os.path.join(folder, filename))
        points.append(data['data'][...].astype(np.float32))
        intensity_features.append(data['intensity'][...].astype(np.float32))
        point_nums.append(data['data_num'][...].astype(np.int32))
    return (np.concatenate(points, axis=0),
            np.concatenate(intensity_features, axis=0),
            np.concatenate(point_nums, axis=0))


def load_all_seg(filelist, v_t_rate=0.5):
    """

    :param filelist:
    :param v_t_rate: val_num / train_num
    :return:train data and val data
    """
    train_occupancy = 100 / (1 + v_t_rate)
    points_train = []
    point_nums_train = []
    labels_seg_train = []
    points_val = []
    point_nums_val = []
    labels_seg_val = []

    folder = os.path.dirname(filelist)
    for line in open(filelist):
        filename = os.path.basename(line.rstrip())
        data = h5py.File(os.path.join(folder, filename))

        for i in range(len(data['data_num'])):

            if random.randint(0, 100) <= train_occupancy:
                points_train.append(data['data'][i][...].astype(np.float32))
                point_nums_train.append(data['data_num'][i][...].astype(np.int32))
                labels_seg_train.append(data['label_seg'][i][...].astype(np.int32))
            else:
                points_val.append(data['data'][i][...].astype(np.float32))
                point_nums_val.append(data['data_num'][i][...].astype(np.int32))
                labels_seg_val.append(data['label_seg'][i][...].astype(np.int32))

    return (np.concatenate(points_train, axis=0),
            np.concatenate(point_nums_train, axis=0),
            np.concatenate(labels_seg_train, axis=0),
            np.concatenate(points_val, axis=0),
            np.concatenate(point_nums_val, axis=0),
            np.concatenate(labels_seg_val, axis=0))


def balance_classes(labels):
    _, inverse, counts = np.unique(labels, return_inverse=True, return_counts=True)
    counts_max = np.amax(counts)
    repeat_num_avg_unique = counts_max / counts
    repeat_num_avg = repeat_num_avg_unique[inverse]
    repeat_num_floor = np.floor(repeat_num_avg)
    repeat_num_probs = repeat_num_avg - repeat_num_floor
    repeat_num = repeat_num_floor + (np.random.rand(repeat_num_probs.shape[0]) < repeat_num_probs)
    return repeat_num.astype(np.int64)


def load_bin(dir):
    print("load bin")
    bin_path = os.path.join(dir, "data_fountain_point.bin")
    points_ele_all = np.fromfile(bin_path, np.float32)

    bin_path = os.path.join(dir, "data_fountain_intensity.bin")
    intensities = np.fromfile(bin_path, np.float32)

    bin_path = os.path.join(dir, "data_fountain_point_num.bin")
    point_nums = np.fromfile(bin_path, np.uint16).astype(int)

    bin_path = os.path.join(dir, "data_fountain_label.bin")
    labels = None
    if os.path.exists(bin_path):
        labels = np.fromfile(bin_path, np.uint8)

    bin_path = os.path.join(dir, "data_fountain_indices.bin")
    indices = None
    if os.path.exists(bin_path):
        indices = np.fromfile(bin_path, np.uint16).astype(int)

    print("create index_length")
    index_length = np.zeros((len(point_nums), 2), int)
    index_sum = 0
    for i in range(len(point_nums)):
        index_length[i][0] = index_sum
        index_length[i][1] = point_nums[i]
        index_sum += point_nums[i]

    return index_length, points_ele_all, intensities, labels, indices