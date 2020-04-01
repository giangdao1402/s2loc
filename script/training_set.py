import torch.utils.data
from data_source import DataSource
from dh_grid import DHGrid
from sphere import Sphere

from tqdm.auto import tqdm, trange
from tqdm.contrib.concurrent import process_map, thread_map
from functools import partial

import pymp

def progresser(sample, grid, auto_position=True, write_safe=False, blocking=True, progress=False):
    sample_sphere = Sphere(sample)
    return sample_sphere.sampleUsingGrid(grid)

class TrainingSet(torch.utils.data.Dataset):
    def __init__(self, data_source, bw=100, training=True):
        self.ds = data_source
        self.bw = bw
        self.is_training = training

        if training:
            (a,p,n) = (self.ds.anchors_training, self.ds.positives_training, self.ds.negatives_training)
        else:
            (a,p,n) = (self.ds.anchors_test, self.ds.positives_test, self.ds.negatives_test)

        self.anchor_features, self.positive_features, self.negative_features = self.__genAllFeatures(bw, a, p, n)

    def __getitem__(self, index):
        anchor = torch.from_numpy(self.anchor_features[index])
        positive = torch.from_numpy(self.positive_features[index])
        negative = torch.from_numpy(self.negative_features[index])
        return anchor, positive, negative

    def __len__(self):
        return len(self.ds)

    def __genAllFeatures(self, bw, anchors, positives, negatives):
        n_ds = len(anchors)
        grid = DHGrid.CreateGrid(bw)
        print("Generating anchor spheres")
        anchor_features = process_map(partial(progresser, grid=grid), anchors, max_workers=32)
        print("Generating positive spheres")
        positive_features = process_map(partial(progresser, grid=grid), positives, max_workers=32)
        print("Generating negative spheres")
        negative_features = process_map(partial(progresser, grid=grid), negatives, max_workers=32)


        print("Generated features")
        return anchor_features, positive_features, negative_features

    def isTraining(self):
        return self.is_training


if __name__ == "__main__":
    ds = DataSource('/home/berlukas/data/spherical/training-set')
    ds.load(100)

    ts = TrainingSet(ds)
    a,p,n = ts.__getitem__(0)
    print("First anchor:\t", a.shape)
    print("First positive:\t", p.shape)
    print("First negative:\t", n.shape)
    print("Total length:\t", ts.__len__())
