#!/usr/bin/env python
# coding: utf-8

# # S2Loc Training
#
# Description: We propose to lear a descriptor of point clouds for global localization.
#
# Author: Lukas Bernreiter (lukas.bernreiter@ieee.org)
#

from data_source import DataSource
from visualize import Visualize
from sphere import Sphere
from model import Model
from loss import TripletLoss, ImprovedTripletLoss
from training_set import TrainingSet
from average_meter import AverageMeter
from data_splitter import DataSplitter

import torch
import torch.nn.functional as F
from torch.utils.tensorboard import SummaryWriter
from torch.autograd import Variable
import torchvision
import torchvision.transforms as transforms
from torch.autograd import Variable
from torch.utils.tensorboard import SummaryWriter

import sys
import time
import math
import numpy as np
import pandas as pd
import open3d as o3d
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from tqdm.auto import tqdm
from scipy import spatial


# ## Load All Data
#
# Load the dataset, project each point cloud on a sphere and derive a function for it.


#ds = DataSource('/home/berlukas/data/spherical/training-set', 1.0)
ds = DataSource('/home/berlukas/data/spherical/training', 1.0)
ds.load(100)

# ## Initialize the model and the training set


torch.cuda.set_device(1)
torch.backends.cudnn.benchmark = True
net = Model().cuda()
restore = False
optimizer = torch.optim.SGD(net.parameters(), lr=5e-3, momentum=0.9)
n_epochs = 20
batch_size = 5 #14
num_workers = 1
descriptor_size = 32
criterion = ImprovedTripletLoss(margin=2, alpha=0.5, margin2=0.2)

result_save = 'triplet_result.txt'
model_save = 'net_params_new_1.pkl'

fp = open(result_save,'w')
n_parameters = sum([p.data.nelement() for p in net.parameters()])
fp.write('Number of params: {}\n'.format(n_parameters))
fp.write('features: [2, 10, 16, 20, 60]\n')
fp.write('bandwidths: [512, 50, 25, 15, 5]\n')
fp.write('batch_size = 16\n')
fp.write('training epoch: 20\n')
fp.write('TripletLoss(margin=2.0\n')
writer = SummaryWriter()

bandwith = 100
train_set = TrainingSet(ds, bandwith)
print("total set size: ", len(train_set))

split = DataSplitter(train_set, shuffle=True)
train_loader, val_loader, test_loader = split.get_split(batch_size=batch_size, num_workers=1)
train_size = split.get_train_size()
val_size = split.get_val_size()
test_size = split.get_test_size()
print("train size: ", train_size)
print("val size: ", val_size)
print("test size: ", test_size)

# ## Train model

def adjust_learning_rate_exp(optimizer, epoch_num, lr=5e-3):
    decay_rate = 0.96
    new_lr = lr * math.pow(decay_rate, epoch_num)
    for param_group in optimizer.param_groups:
        param_group['lr'] = new_lr

    return new_lr

val_accs = AverageMeter()
loss_ = 0

def accuracy(dista, distb):
    margin = 0
    pred = (dista - distb - margin).cpu().data
    acc = ((pred < 0).sum()).float()/dista.size(0)
    return acc

def train(net, criterion, optimizer, writer, epoch, n_iter, loss_, t0):
    net.train()
    for batch_idx, (data1, data2, data3) in enumerate(train_loader):
        data1, data2, data3 = data1.cuda().float(), data2.cuda().float(), data3.cuda().float()
        embedded_a, embedded_p, embedded_n = net(data1, data2, data3)
        optimizer.zero_grad()

        dista, distb, loss_triplet, loss_total = criterion(embedded_a, embedded_p, embedded_n)
        loss_embedd = embedded_a.norm(2) + embedded_p.norm(2) + embedded_n.norm(2)
        loss = loss_triplet + 0.001 * loss_embedd
        #loss = loss_triplet

        loss.backward()
        optimizer.step()
        loss_ += loss_total.item()

        writer.add_scalar('Train/Loss_Triplet', loss_triplet, n_iter)
        writer.add_scalar('Train/Loss_Embedd', loss_embedd, n_iter)
        writer.add_scalar('Train/Loss', loss, n_iter)
        n_iter += 1

        if batch_idx % 100 == 99:
            t1 = time.time()
            print('[Epoch %d, Batch %4d] loss: %.5f time: %.5f lr: %.3e' %
                (epoch + 1, batch_idx + 1, loss_ / 100, (t1-t0) / 60, lr))
            t0 = t1
            loss_ = 0.0
    return n_iter

def validate(net, criterion, optimizer, writer, epoch, n_iter):
    net.eval()
    with torch.no_grad():
        for batch_idx, (data1, data2, data3) in enumerate(val_loader):
            data1, data2, data3 = data1.cuda().float(), data2.cuda().float(), data3.cuda().float()
            embedded_a, embedded_p, embedded_n = net(data1, data2, data3)
            optimizer.zero_grad()

            dista, distb, loss_triplet, loss_total = criterion(embedded_a, embedded_p, embedded_n)
            loss_embedd = embedded_a.norm(2) + embedded_p.norm(2) + embedded_n.norm(2)
            loss = loss_triplet + 0.001 * loss_embedd


            acc = accuracy(dista, distb)
            val_accs.update(acc, data1.size(0))
            writer.add_scalar('Validation/Loss_Triplet', loss_triplet, n_iter)
            writer.add_scalar('Validation/Loss_Embedd', loss_embedd, n_iter)
            writer.add_scalar('Validation/Loss', loss, n_iter)
            writer.add_scalar('Validation/Accuracy', val_accs.avg, n_iter)
            n_iter += 1
    return n_iter

def test(net, criterion, writer):
    with open('test_indices.txt','wb') as f:
        np.savetxt(f, np.array(split.test_indices), fmt='%d')

    n_iter = 0
    net.eval()
    test_accs = AverageMeter()
    test_pos_dist = AverageMeter()
    test_neg_dist = AverageMeter()
    anchor_embeddings = []
    positive_embeddings = []
    #anchor_embeddings = np.empty([test_size, descriptor_size])
    #positive_embeddings = np.empty([test_size, descriptor_size])
    for batch_idx, (data1, data2, data3) in enumerate(test_loader):
            embedded_a, embedded_p, embedded_n = net(data1.cuda().float(), data2.cuda().float(), data3.cuda().float())
            dist_to_pos, dist_to_neg, loss, loss_total = criterion(embedded_a, embedded_p, embedded_n)
            writer.add_scalar('Test/Loss', loss, n_iter)

            acc = accuracy(dist_to_pos, dist_to_neg)
            test_accs.update(acc, data1.size(0))
            test_pos_dist.update(dist_to_pos.cpu().data.numpy().sum())
            test_neg_dist.update(dist_to_neg.cpu().data.numpy().sum())

            writer.add_scalar('Test/Accuracy', test_accs.avg, n_iter)
            writer.add_scalar('Test/Distance/Positive', test_pos_dist.avg, n_iter)
            writer.add_scalar('Test/Distance/Negative', test_neg_dist.avg, n_iter)

            anchor_embeddings.append(embedded_a.cpu().data.numpy().reshape([1,-1]))
            positive_embeddings.append(embedded_p.cpu().data.numpy().reshape([1,-1]))
            n_iter = n_iter + 1

    desc_anchors = np.array(anchor_embeddings).reshape([test_size, descriptor_size])
    desc_positives = np.array(positive_embeddings).reshape([test_size, descriptor_size])
    print(np.array(desc_positives).shape)

    sys.setrecursionlimit(50000)
    tree = spatial.KDTree(desc_positives)
    p_norm = 2
    max_pos_dist = 0.05
    max_anchor_dist = 1
    for n_nearest_neighbors in range(1,21):
        pos_count = 0
        anchor_count = 0
        idx_count = 0
        for idx in range(test_size):
            nn_dists, nn_indices = tree.query(desc_anchors[idx,:], p = p_norm, k = n_nearest_neighbors)
            nn_indices = [nn_indices] if n_nearest_neighbors == 1 else nn_indices

            for nn_i in nn_indices:
                if (nn_i >= test_size):
                    break;
                dist = spatial.distance.euclidean(desc_positives[nn_i,:], desc_positives[idx,:])
                if (dist <= max_pos_dist):
                    pos_count = pos_count + 1;
                    break
            for nn_i in nn_indices:
                if (nn_i >= test_size):
                    break;
                dist = spatial.distance.euclidean(desc_positives[nn_i,:], desc_anchors[idx,:])
                if (dist <= max_anchor_dist):
                    anchor_count = anchor_count + 1;
                    break
            for nn_i in nn_indices:
                if (nn_i == idx):
                    idx_count = idx_count + 1;
                    break
        pos_precision = (pos_count*1.0) / test_size
        anchor_precision = (anchor_count*1.0) / test_size
        idx_precision = (idx_count*1.0) / test_size
        print(f'Precision pos: {pos_precision} for {n_nearest_neighbors} neighbors.');
        print(f'Precision anchor: {anchor_precision} for {n_nearest_neighbors} neighbors.');
        print(f'Precision idx: {idx_precision} for {n_nearest_neighbors} neighbors.');
        writer.add_scalar('Test/Precision/Positive_Distance', pos_precision, n_nearest_neighbors)
        writer.add_scalar('Test/Precision/Anchor_Distance', anchor_precision, n_nearest_neighbors)
        writer.add_scalar('Test/Precision/Index_Count', idx_precision, n_nearest_neighbors)

if not restore:
    train_iter = 0
    val_iter = 0
    loss_ = 0.0
    print(f'Starting training using {n_epochs} epochs');
    for epoch in tqdm(range(n_epochs)):
        lr = adjust_learning_rate_exp(optimizer, epoch_num=epoch)
        t0 = time.time()

        train_iter = train(net, criterion, optimizer, writer, epoch, train_iter, loss_, t0)

        val_iter = validate(net, criterion, optimizer, writer, epoch, val_iter)

        writer.add_scalar('Train/lr', lr, epoch)

    print("Training finished!")
    torch.save(net.state_dict(), model_save)
else:
    net.load_state_dict(torch.load(model_save))

## Test

print("Starting testing...")
test(net, criterion, writer)
print("Testing finished!")
writer.close()
fp.close()
