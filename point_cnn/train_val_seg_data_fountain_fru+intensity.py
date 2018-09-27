#!/usr/bin/python3
"""Training and Validation On Segmentation Task."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import sys
import math
import random
import shutil
import argparse
import importlib
from data_utils import data_utils
import numpy as np
import pointfly as pf
import tensorflow as tf
from datetime import datetime


def load_bin(dir):
    print("load bin")
    bin_path = os.path.join(dir, "data_fountain_point.bin")
    points_ele_all = np.fromfile(bin_path, np.float32)

    bin_path = os.path.join(dir, "data_fountain_intensity.bin")
    intensities = np.fromfile(bin_path, np.float32)

    bin_path = os.path.join(dir, "data_fountain_point_num.bin")
    point_nums = np.fromfile(bin_path, np.uint16).astype(int)

    bin_path = os.path.join(dir, "data_fountain_label.bin")
    labels = np.fromfile(bin_path, np.uint8)

    print("create index_length")
    index_length = np.zeros((len(point_nums), 2), int)
    index_sum = 0
    for i in range(len(point_nums)):
        index_length[i][0] = index_sum
        index_length[i][1] = point_nums[i]
        index_sum += point_nums[i]

    return index_length, points_ele_all, intensities, labels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dir_train', '-t', help='Path to dir of train set', required=True)
    parser.add_argument('--dir_val', '-v', help='Path to dir of val set', required=False)
    parser.add_argument('--load_ckpt', '-l', help='Path to a check point file for load')
    parser.add_argument('--save_folder', '-s', help='Path to folder for saving check points and summary', required=True)
    parser.add_argument('--model', '-m', help='Model to use', required=True)
    parser.add_argument('--setting', '-x', help='Setting to use', required=True)
    args = parser.parse_args()

    time_string = datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
    root_folder = os.path.join(args.save_folder, '%s_%s_%d_%s' % (args.model, args.setting, os.getpid(), time_string))
    if not os.path.exists(root_folder):
        os.makedirs(root_folder)

    print('PID:', os.getpid())

    print(args)

    model = importlib.import_module(args.model)
    setting_path = os.path.join(os.path.dirname(__file__), args.model)
    sys.path.append(setting_path)
    print(setting_path)
    setting = importlib.import_module(args.setting)

    num_epochs = setting.num_epochs
    batch_size = setting.batch_size
    sample_num = setting.sample_num
    step_val = setting.step_val
    num_parts = setting.num_parts
    label_weights_list = setting.label_weights
    scaling_range = setting.scaling_range
    scaling_range_val = setting.scaling_range_val
    jitter = setting.jitter
    jitter_val = setting.jitter_val

    # Prepare inputs
    print('{}-Preparing datasets...'.format(datetime.now()))

    if args.dir_val is None:
        print("only load train")
        index_length_train, points_ele_train, intensities_train, labels_train = load_bin(args.dir_train)
        index_length_val = index_length_train
        points_ele_val = points_ele_train
        intensities_val = intensities_train
        labels_val = labels_train
    else:
        print("load train and val")
        index_length_train, points_ele_train, intensities_train, labels_train = load_bin(args.dir_train)
        index_length_val, points_ele_val, intensities_val, labels_val = load_bin(args.dir_val)

    # shuffle
    index_length_train = data_utils.index_shuffle(index_length_train)
    index_length_val = data_utils.index_shuffle(index_length_val)

    num_train = index_length_train.shape[0]
    point_num = max(np.max(index_length_train[:, 1]), np.max(index_length_val[:, 1]))
    num_val = index_length_val.shape[0]

    print('{}-{:d}/{:d} training/validation samples.'.format(datetime.now(), num_train, num_val))
    batch_num = (num_train * num_epochs + batch_size - 1) // batch_size
    print('{}-{:d} training batches.'.format(datetime.now(), batch_num))
    batch_num_val = math.ceil(num_val / batch_size)
    print('{}-{:d} testing batches per test.'.format(datetime.now(), batch_num_val))

    ######################################################################
    # Placeholders
    indices = tf.placeholder(tf.int32, shape=(None, None, 2), name="indices")
    xforms = tf.placeholder(tf.float32, shape=(None, 3, 3), name="xforms")
    rotations = tf.placeholder(tf.float32, shape=(None, 3, 3), name="rotations")
    jitter_range = tf.placeholder(tf.float32, shape=(1), name="jitter_range")
    global_step = tf.Variable(0, trainable=False, name='global_step')
    is_training = tf.placeholder(tf.bool, name='is_training')

    pts = tf.placeholder(tf.float32, shape=(None, point_num, setting.point_dim), name='pts')
    fts = tf.placeholder(tf.float32, shape=(None, point_num, setting.extra_dim), name='fts')
    labels_seg = tf.placeholder(tf.int32, shape=(None, point_num), name='labels_seg')
    labels_weights = tf.placeholder(tf.float32, shape=(None, point_num), name='labels_weights')

    ######################################################################

    # Set Inputs(points,features_sampled)
    features_sampled = None

    if setting.extra_dim == 1:
        points = pts
        features = fts

        if setting.use_extra_features:
            features_sampled = tf.gather_nd(features, indices=indices, name='features_sampled')

    elif setting.extra_dim == 0:
        points = pts

    points_sampled = tf.gather_nd(points, indices=indices, name='points_sampled')
    points_augmented = pf.augment(points_sampled, xforms, jitter_range)

    labels_sampled = tf.gather_nd(labels_seg, indices=indices, name='labels_sampled')
    labels_weights_sampled = tf.gather_nd(labels_weights, indices=indices, name='labels_weight_sampled')

    # Build net
    net = model.Net(points_augmented, features_sampled, None, None, num_parts, is_training, setting)
    logits, probs = net.logits, net.probs

    # Define Loss Func
    loss_op = tf.losses.sparse_softmax_cross_entropy(labels=labels_sampled, logits=logits,
                                                     weights=labels_weights_sampled)
    _ = tf.summary.scalar('loss/train_seg', tensor=loss_op, collections=['train'])

    # for vis t1 acc
    t_1_acc_op = pf.top_1_accuracy(probs, labels_sampled)
    _ = tf.summary.scalar('t_1_acc/train_seg', tensor=t_1_acc_op, collections=['train'])
    # for vis instance acc
    t_1_acc_instance_op = pf.top_1_accuracy(probs, labels_sampled, labels_weights_sampled, 0.6)
    _ = tf.summary.scalar('t_1_acc/train_seg_instance', tensor=t_1_acc_instance_op, collections=['train'])
    # for vis other acc
    t_1_acc_others_op = pf.top_1_accuracy(probs, labels_sampled, labels_weights_sampled, 0.6, "less")
    _ = tf.summary.scalar('t_1_acc/train_seg_others', tensor=t_1_acc_others_op, collections=['train'])

    loss_val_avg = tf.placeholder(tf.float32)
    _ = tf.summary.scalar('loss/val_seg', tensor=loss_val_avg, collections=['val'])

    t_1_acc_val_avg = tf.placeholder(tf.float32)
    _ = tf.summary.scalar('t_1_acc/val_seg', tensor=t_1_acc_val_avg, collections=['val'])
    t_1_acc_val_instance_avg = tf.placeholder(tf.float32)
    _ = tf.summary.scalar('t_1_acc/val_seg_instance', tensor=t_1_acc_val_instance_avg, collections=['val'])
    t_1_acc_val_others_avg = tf.placeholder(tf.float32)
    _ = tf.summary.scalar('t_1_acc/val_seg_others', tensor=t_1_acc_val_others_avg, collections=['val'])

    reg_loss = setting.weight_decay * tf.losses.get_regularization_loss()

    # lr decay
    lr_exp_op = tf.train.exponential_decay(setting.learning_rate_base, global_step, setting.decay_steps,
                                           setting.decay_rate, staircase=True)
    lr_clip_op = tf.maximum(lr_exp_op, setting.learning_rate_min)
    _ = tf.summary.scalar('learning_rate', tensor=lr_clip_op, collections=['train'])

    # Optimizer
    if setting.optimizer == 'adam':
        optimizer = tf.train.AdamOptimizer(learning_rate=lr_clip_op, epsilon=setting.epsilon)
    elif setting.optimizer == 'momentum':
        optimizer = tf.train.MomentumOptimizer(learning_rate=lr_clip_op, momentum=0.9, use_nesterov=True)
    update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)

    with tf.control_dependencies(update_ops):

        train_op = optimizer.minimize(loss_op + reg_loss, global_step=global_step)

    init_op = tf.group(tf.global_variables_initializer(), tf.local_variables_initializer())

    saver = tf.train.Saver(max_to_keep=None)

    # backup this file, model and setting
    if not os.path.exists(os.path.join(root_folder, args.model)):
        os.makedirs(os.path.join(root_folder, args.model))
    shutil.copy(__file__, os.path.join(root_folder, os.path.basename(__file__)))
    shutil.copy(os.path.join(os.path.dirname(__file__), args.model + '.py'),
                os.path.join(root_folder, args.model + '.py'))
    shutil.copy(os.path.join(os.path.dirname(__file__), args.model.split("_")[0] + "_kitti" + '.py'),
                os.path.join(root_folder, args.model.split("_")[0] + "_kitti" + '.py'))
    shutil.copy(os.path.join(setting_path, args.setting + '.py'),
                os.path.join(root_folder, args.model, args.setting + '.py'))

    folder_ckpt = os.path.join(root_folder, 'ckpts')
    if not os.path.exists(folder_ckpt):
        os.makedirs(folder_ckpt)

    folder_summary = os.path.join(root_folder, 'summary')
    if not os.path.exists(folder_summary):
        os.makedirs(folder_summary)

    parameter_num = np.sum([np.prod(v.shape.as_list()) for v in tf.trainable_variables()])
    print('{}-Parameter number: {:d}.'.format(datetime.now(), parameter_num))

    # Session Run
    with tf.Session() as sess:
        summaries_op = tf.summary.merge_all('train')
        summaries_val_op = tf.summary.merge_all('val')
        summary_writer = tf.summary.FileWriter(folder_summary, sess.graph)

        sess.run(init_op)

        # Load the model
        if args.load_ckpt is not None:
            saver.restore(sess, args.load_ckpt)
            print('{}-Checkpoint loaded from {}!'.format(datetime.now(), args.load_ckpt))

        for batch_idx in range(batch_num):
            if (batch_idx != 0 and batch_idx % step_val == 0) or batch_idx == batch_num - 1:
                ######################################################################
                # Validation
                filename_ckpt = os.path.join(folder_ckpt, 'iter')
                saver.save(sess, filename_ckpt, global_step=global_step)
                print('{}-Checkpoint saved to {}!'.format(datetime.now(), filename_ckpt))

                losses_val = []
                t_1_accs = []
                t_1_accs_instance = []
                t_1_accs_others = []

                for batch_val_idx in range(math.ceil(num_val / batch_size)):
                    start_idx = batch_size * batch_val_idx
                    end_idx = min(start_idx + batch_size, num_val)
                    batch_size_val = end_idx - start_idx
                    index_length_val_batch = index_length_val[start_idx:end_idx]

                    points_batch = np.zeros((batch_size_val, point_num, 3), np.float32)
                    intensity_batch = np.zeros((batch_size_val, point_num, 1), np.float32)
                    points_num_batch = np.zeros(batch_size_val, np.int32)
                    labels_batch = np.zeros((batch_size_val, point_num), np.int32)

                    for i, index_length in enumerate(index_length_val_batch):
                        points_batch[i, 0:index_length[1], :] = \
                            points_ele_val[index_length[0] * 3:
                                           index_length[0] * 3 + index_length[1] * 3].reshape(index_length[1], 3)

                        intensity_batch[i, 0:index_length[1], :] = \
                            intensities_val[index_length[0]:
                                            index_length[0] + index_length[1]].reshape(index_length[1], 1)

                        points_num_batch[i] = index_length[1].astype(np.int32)

                        labels_batch[i, 0:index_length[1]] = \
                            labels_val[index_length[0]:index_length[0] + index_length[1]].astype(np.int32)

                    weights_batch = np.array(label_weights_list)[labels_batch]

                    xforms_np, rotations_np = pf.get_xforms(batch_size_val, scaling_range=scaling_range_val)

                    sess_op_list = [loss_op, t_1_acc_op, t_1_acc_instance_op, t_1_acc_others_op]

                    sess_feed_dict = {pts: points_batch,
                                      fts: intensity_batch,
                                      indices: pf.get_indices(batch_size_val, sample_num, points_num_batch),
                                      xforms: xforms_np,
                                      rotations: rotations_np,
                                      jitter_range: np.array([jitter_val]),
                                      labels_seg: labels_batch,
                                      labels_weights: weights_batch,
                                      is_training: False}

                    loss_val, t_1_acc_val, t_1_acc_val_instance, t_1_acc_val_others = sess.run(sess_op_list,
                                                                                               feed_dict=sess_feed_dict)
                    print('{}-[Val  ]-Iter: {:06d}  Loss: {:.4f} T-1 Acc: {:.4f}'.format(datetime.now(), batch_val_idx,
                                                                                         loss_val, t_1_acc_val))

                    losses_val.append(loss_val * batch_size_val)
                    t_1_accs.append(t_1_acc_val * batch_size_val)
                    t_1_accs_instance.append(t_1_acc_val_instance * batch_size_val)
                    t_1_accs_others.append(t_1_acc_val_others * batch_size_val)

                loss_avg = sum(losses_val) / num_val
                t_1_acc_avg = sum(t_1_accs) / num_val
                t_1_acc_instance_avg = sum(t_1_accs_instance) / num_val
                t_1_acc_others_avg = sum(t_1_accs_others) / num_val

                summaries_feed_dict = {loss_val_avg: loss_avg,
                                       t_1_acc_val_avg: t_1_acc_avg,
                                       t_1_acc_val_instance_avg: t_1_acc_instance_avg,
                                       t_1_acc_val_others_avg: t_1_acc_others_avg}

                summaries_val = sess.run(summaries_val_op, feed_dict=summaries_feed_dict)
                summary_writer.add_summary(summaries_val, batch_idx)

                print('{}-[Val  ]-Average:      Loss: {:.4f} T-1 Acc: {:.4f}'
                      .format(datetime.now(), loss_avg, t_1_acc_avg))

                ######################################################################

            ######################################################################
            # Training
            start_idx = (batch_size * batch_idx) % num_train
            end_idx = min(start_idx + batch_size, num_train)
            batch_size_train = end_idx - start_idx

            index_length_train_batch = index_length_train[start_idx:end_idx]
            points_batch = np.zeros((batch_size_train, point_num, 3), np.float32)
            intensity_batch = np.zeros((batch_size_train, point_num, 1), np.float32)
            points_num_batch = np.zeros(batch_size_train, np.int32)
            labels_batch = np.zeros((batch_size_train, point_num), np.int32)

            for i, index_length in enumerate(index_length_train_batch):
                points_batch[i, 0:index_length[1], :] = \
                    points_ele_train[index_length[0] * 3:
                                     index_length[0] * 3 + index_length[1] * 3].reshape(index_length[1], 3)

                intensity_batch[i, 0:index_length[1], :] = \
                    intensities_train[index_length[0]:
                                      index_length[0] + index_length[1]].reshape(index_length[1], 1)

                points_num_batch[i] = index_length[1].astype(np.int32)

                labels_batch[i, 0:index_length[1]] = \
                    labels_train[index_length[0]:index_length[0] + index_length[1]].astype(np.int32)

            weights_batch = np.array(label_weights_list)[labels_batch]

            if start_idx + batch_size_train == num_train:
                index_length_train = data_utils.index_shuffle(index_length_train)

            offset = int(random.gauss(0, sample_num // 8))
            offset = max(offset, -sample_num // 4)
            offset = min(offset, sample_num // 4)
            sample_num_train = sample_num + offset
            xforms_np, rotations_np = pf.get_xforms(batch_size_train, scaling_range=scaling_range)

            sess_op_list = [train_op, loss_op, t_1_acc_op, t_1_acc_instance_op, t_1_acc_others_op, summaries_op]

            sess_feed_dict = {pts: points_batch,
                              fts: intensity_batch,
                              indices: pf.get_indices(batch_size_train, sample_num_train, points_num_batch),
                              xforms: xforms_np,
                              rotations: rotations_np,
                              jitter_range: np.array([jitter]),
                              labels_seg: labels_batch,
                              labels_weights: weights_batch,
                              is_training: True}

            _, loss, t_1_acc, t_1_acc_instance, t_1_acc_others, summaries = sess.run(sess_op_list,
                                                                                     feed_dict=sess_feed_dict)
            print('{}-[Train]-Iter: {:06d}  Loss_seg: {:.4f} T-1 Acc: {:.4f}'
                  .format(datetime.now(), batch_idx, loss, t_1_acc))

            summary_writer.add_summary(summaries, batch_idx)

            ######################################################################
        print('{}-Done!'.format(datetime.now()))


if __name__ == '__main__':
    main()
