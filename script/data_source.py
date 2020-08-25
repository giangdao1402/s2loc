from plyfile import PlyData, PlyElement
import glob
import numpy as np
from os import listdir

class DataSource:
    def __init__(self, path_to_datasource, cache = -1, skip_nth=-1):
        self.datasource = path_to_datasource
        self.anchors = None
        self.anchor_sph_images = None
        self.positives = None
        self.positive_sph_images = None
        self.negatives = None
        self.negative_sph_images = None
        self.ds_total_size = 0
        self.cache = cache
        self.start_cached = 0
        self.end_cached = 0
        self.all_anchor_files = []
        self.all_anchor_image_files = []
        self.all_positive_files = []
        self.all_positive_image_files = []
        self.all_negative_files = []
        self.all_negative_image_files = []

    def load(self, n = -1):
        path_anchor = self.datasource + "/training_anchor_pointclouds/"
        path_anchor_images = self.datasource + "/training_anchor_sph_images/"
        path_positives = self.datasource + "/training_positive_pointclouds/"
        path_positive_images = self.datasource + "/training_positive_sph_images/"
        path_negatives = self.datasource + "/training_negative_pointclouds/"
        path_negative_images = self.datasource + "/training_negative_sph_images/"

        print(f"Loading anchors from:\t{path_anchor} and {path_anchor_images}")
        self.all_anchor_files = sorted(glob.glob(path_anchor + '*.ply'))
        self.anchors = self.loadDataset(self.all_anchor_files, n, self.cache)
        self.all_anchor_image_files = sorted(glob.glob(path_anchor_images + '*.ply'))
        self.anchor_sph_images = self.loadDataset(self.all_anchor_image_files, n, self.cache)
        print(f"Loading positives from:\t{path_positives} and {path_positive_images}")
        self.all_positive_files = sorted(glob.glob(path_positives + '*.ply'))
        self.positives = self.loadDataset(self.all_positive_files, n, self.cache)
        self.all_positive_image_files = sorted(glob.glob(path_positive_images + '*.ply'))
        self.positive_sph_images = self.loadDataset(self.all_positive_image_files, n, self.cache)
        print(f"Loading negatives from:\t{path_negatives} and {path_negative_images}")
        self.all_negative_files = sorted(glob.glob(path_negatives + '*.ply'))
        self.negatives = self.loadDataset(self.all_negative_files, n, self.cache)
        self.all_negative_image_files = sorted(glob.glob(path_negative_images + '*.ply'))
        self.negative_sph_images = self.loadDataset(self.all_negative_image_files, n, self.cache)

        print("Done loading dataset.")
        print(f"\tAnchor point clouds total: \t{len(self.anchors)}")
        print(f"\tAnchor images total: \t\t{len(self.anchor_sph_images)}")
        print(f"\tPositive point clouds total: \t{len(self.positives)}")
        print(f"\tPositive images total: \t\t{len(self.positive_sph_images)}")
        print(f"\tNegative point clouds total: \t{len(self.negatives)}")
        print(f"\tNegative images total: \t\t{len(self.negative_sph_images)}")

    def loadDataset(self, all_files, n, cache):
        idx = 0
        self.ds_total_size = len(all_files)
        n_ds = min(self.ds_total_size, n) if n > 0 else self.ds_total_size
        dataset = [None] * n_ds
        skipping = 0
        n_iter = 0
        for ply_file in all_files:
            n_iter = n_iter + 1
            if n_iter > n:
                break;

            if self.skip_nth != -1 and skipping > 0 and skipping <= self.skip_nth:
                skipping = skipping + 1
                continue;

            dataset[idx] = self.loadPointCloudFromPath(ply_file) if idx < cache else ply_file
            idx = idx + 1
            skipping = 1
        self.end_cached = cache
        if self.skip_nth != -1:
            dataset = list(filter(None.__ne__, dataset))

        return dataset

    def loadDatasetPathOnly(self, path_to_dataset, n):
        all_files = sorted(glob.glob(path_to_dataset + '*.ply'))
        n_ds = min(n_files, n) if n > 0 else n_files
        dataset = all_files[:,n_ds]
        return dataset

    def loadPointCloudFromPath(self, path_to_point_cloud):
        plydata = PlyData.read(path_to_point_cloud)
        vertex = plydata['vertex']
        x = vertex['x']
        y = vertex['y']
        z = vertex['z']
        if 'scalar' in vertex._property_lookup:
            i = vertex['scalar']
        elif 'intensity' in vertex._property_lookup:
            i = vertex['intensity']
        else:
            i = plydata['vertex'][plydata.elements[0].properties[3].name]

        return np.concatenate((x,y,z,i), axis=0).reshape(4, len(x)).transpose()

    def writePointCloudToPath(self, cloud, path_to_point_cloud):
        types = [('x', 'f4'), ('y', 'f4'), ('z', 'f4'), ('i', 'f4')]
        vertex = np.array(cloud, types)
        import pdb; pdb.set_trace()
        el = PlyElement.describe(vertex, 'vertex')
        PlyData([el], text=True).write(path_to_point_cloud)

    def writeFeatureCloudToPath(self, cloud, path_to_point_cloud):
        types = [('x', 'f4'), ('y', 'f4')]
        vertex = np.array(cloud, types)
        import pdb; pdb.set_trace()
        el = PlyElement.describe(vertex, 'vertex')
        PlyData([el], text=True).write(path_to_point_cloud)

    def size(self):
        return len(self.anchors)

    def __len__(self):
        return self.size()

    def cache_next(self, index):
        prev_end = self.end_cached
        self.end_cached = min(self.size(), index+self.cache)
        for idx in range(prev_end, self.end_cached):
            self.anchors[idx], self.positives[idx], self.negatives[idx] = self.load_clouds_directly(idx)
        return prev_end, self.end_cached

    def free_to_start_cached(self):
        for idx in range(0, self.start_cached):
            self.anchors[idx] = self.all_anchor_files[idx]
            self.positives[idx] = self.all_positive_files[idx]
            self.negatives[idx] = self.all_negative_files[idx]

    def get_all_cached(self):
        return self.get_cached(self.start_cached, self.end_cached)

    def get_cached(self, start, end):
        assert start <= end
        start = max(0, start)
        end = min(self.ds_total_size, end)

        return self.anchors[start:end], \
               self.positives[start:end], \
               self.negatives[start:end]

    def load_clouds_directly(self, idx):
        print(f'Requesting direct index {idx} of size {len(self.anchors)}')
        anchor = self.loadPointCloudFromPath(self.anchors[idx]) if isinstance(self.anchors[idx], str) else self.anchors[idx]
        positive = self.loadPointCloudFromPath(self.positives[idx]) if isinstance(self.positives[idx], str) else self.positives[idx]
        negative = self.loadPointCloudFromPath(self.negatives[idx]) if isinstance(self.negatives[idx], str) else self.negatives[idx]
        return anchor, positive, negative

if __name__ == "__main__":
    #ds = DataSource("/mnt/data/datasets/Spherical/training", 10)
    ds = DataSource("/tmp/training", 10)
    ds.load(100)

    a,p,n = ds.get_all_cached()
    print(f'len of initial cache {len(a)} of batch [{ds.start_cached}, {ds.end_cached}]')
    print("Caching next batch...")
    ds.cache_next(25)
    a,p,n = ds.get_all_cached()
    print(f'len of next cache {len(a)} of batch [{ds.start_cached}, {ds.end_cached}]')
