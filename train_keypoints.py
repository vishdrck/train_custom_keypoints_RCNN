import json
import os

import albumentations  # Library for augmentation
import cv2
import numpy as np
import torch
import torchvision
from torch.utils.data import Dataset, DataLoader
from torchvision.models.detection.rpn import AnchorGenerator
from torchvision.transforms import functional as func

from engine import train_one_epoch, evaluate
from utils import collate_fn


def train_transform():
    return albumentations.Compose([
        albumentations.Sequential([
            albumentations.RandomRotate90(p=1),  # Random rotation of an image by 90 degrees zero or more times
            albumentations.RandomBrightnessContrast(
                brightness_limit=0.3,
                contrast_limit=0.3,
                brightness_by_max=True,
                always_apply=False,
                p=1
            ),
        ], p=1)
    ],
        keypoint_params=albumentations.KeypointParams(format='xy'),
        bbox_params=albumentations.BboxParams(format='pascal_voc', label_fields=['bboxes_labels'])
        # Bboxes should have labels
    )


class ClassDataset(Dataset):
    def __init__(self, root, transform=None, demo=False):
        self.root = root
        self.transform = transform
        self.demo = demo  # use demo=True if you need transformed and original images
        self.images_files = sorted(os.listdir(os.path.join(root, "images")))
        self.annotation_files = sorted(os.listdir(os.path.join(root, "annotations")))

    def __getitem__(self, idx):
        img_path = os.path.join(self.root, "images", self.images_files[idx])
        annotations_path = os.path.join(self.root, "annotations", self.annotation_files[idx])
        img_original = cv2.imread(img_path)
        img_original = cv2.cvtColor(img_original, cv2.COLOR_BGR2RGB)

        with open(annotations_path) as f:
            data = json.load(f)
            bboxes_original = data['bboxes']
            keypoints_original = data['keypoints']

            # All objects are glue tubes
            bboxes_labels_original = ['Glue tube' for _ in bboxes_original]

            # Converting keypoints from [x,y,visibility] format to [x,y] format + flattening nested list of keypoints
            # For example: if we have the following list of keypoints for three objects (each object has 2 keypoints)
            # [[obj1_kp1, obj1_kp2], [obj2_kp1, obj2_kp2], [obj3_kp1, obj3_kp2]] where each keypoint is in [x,y] format
            # Then we need to convert it to the following list:
            # [obj1_kp1, obj1_kp2, obj2_kp1, obj2_kp2, obj3_kp1, obj3_kp2]
            if self.transform:
                keypoints_original_flattened = [el[0:2] for kp in keypoints_original for el in kp]

                # Apply augmentation
                transformed = self.transform(
                    image=img_original,
                    bboxes=bboxes_original,
                    bboxes_labels=bboxes_labels_original,
                    keypoints=keypoints_original_flattened)
                img = transformed['image']
                bboxes = transformed['bboxes']

                # Unflattering list transformed['keypoints'] For example, if we have the following list of keypoints
                # for three objects (each object has two keypoints) [obj1_kp1, obj1_kp2, obj2_kp1, obj2_kp2,
                # obj3_kp1, obj3_kp2] where each keypoint is in [x,y] format Then we need to convert it to the
                # following list [[obj1_kp1, obj1_kp2], [obj2_kp1, obj2_kp2], [obj3_kp1, obj3_kp2]]
                keypoints_transformed_unflattened = np.reshape(np.array(transformed['keypoints']), (-1, 2, 2)).tolist()

                # Converting transformed keypoints from [x,y] format to [x,y,visibility] format
                # by appending original visibilities to transformed coordinates of keypoints
                keypoints = []
                for o_idx, obj in enumerate(keypoints_transformed_unflattened):  # Iterating over objects
                    obj_keypoints = []
                    for k_idx, kp in enumerate(obj):  # Iterating over keypoint in each object
                        # kp - coordinates of keypoints
                        # keypoints_original[o_idx][k_idx][2] - original visibility of keypoint
                        obj_keypoints.append(kp + [keypoints_original[o_idx][k_idx][2]])
                    keypoints.append(obj_keypoints)
            else:
                img, bboxes, keypoints = img_original, bboxes_original, keypoints_original

            # Convert everything into a torch tensor
            bboxes = torch.as_tensor(bboxes, dtype=torch.float32)
            target = {}
            target['boxes'] = bboxes
            target['labels'] = torch.as_tensor([1 for _ in bboxes], dtype=torch.int64)  # all objects are glue tubes
            target['image_id'] = torch.tensor([idx])
            target['area'] = (bboxes[:, 3] - bboxes[:, 1]) * (bboxes[:, 2] - bboxes[:, 0])
            target['isCrowed'] = torch.zeros(len(bboxes), dtype=torch.int64)
            target['keypoints'] = torch.as_tensor(keypoints, dtype=torch.float32)
            img = func.to_tensor(img)

            bboxes_original = torch.as_tensor(bboxes_original, dtype=torch.float32)
            target_original = {}
            target_original['boxes'] = bboxes_original
            target_original['labels'] = torch.as_tensor([1 for _ in bboxes_original],
                                                        dtype=torch.int64)  # all objects are glue tubes
            target_original['image_id'] = torch.tensor([idx])
            target_original['area'] = (bboxes_original[:, 3] - bboxes_original[:, 1]) * (
                    bboxes_original[:, 2] - bboxes_original[:, 0])
            target_original['isCrowed'] = torch.zeros(len(bboxes_original), dtype=torch.int64)
            target_original['keypoints'] = torch.as_tensor(keypoints_original, dtype=torch.float32)
            img_original = func.to_tensor(img_original)

            if self.demo:
                return img, target, img_original, target_original
            else:
                return img, target

    def __len__(self):
        return len(self.images_files)


KEYPOINTS_FOLDER_TRAIN = 'glue_tubes_keypoints_dataset_134imgs/train'
dataset = ClassDataset(KEYPOINTS_FOLDER_TRAIN, transform=train_transform(), demo=True)
data_loader = DataLoader(dataset, batch_size=1, shuffle=True, collate_fn=collate_fn)
#
iterator = iter(data_loader)
batch = next(iterator)


#
# print("Original target:\n", batch[3], "\n\n")
# print("Transformed targets:\n", batch[1])
#
# keypoints_classes_ids2names = {0: 'Head', 1: 'Tail'}
#
#
# def visualize(image, bboxes, keypoints, image_original=None, bboxes_original=None, keypoints_original=None):
#     fontsize = 18
#
#     for bbox in bboxes:
#         start_point = (bbox[0], bbox[1])
#         end_point = (bbox[2], bbox[3])
#         image = cv2.rectangle(image.copy(), start_point, end_point, (0, 255, 0), 2)
#
#     for kps in keypoints:
#         for idx, kp in enumerate(kps):
#             image = cv2.circle(image.copy(), tuple(kp), 5, (255, 0, 0), 10)
#             image = cv2.putText(image.copy(), " " + keypoints_classes_ids2names[idx], tuple(kp),
#                                 cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 0, 0), 3, cv2.LINE_AA)
#
#     if image_original is None and keypoints_original is None:
#         plt.figure(figsize=(40, 40))
#         plt.imshow(image)
#
#     else:
#         for bbox in bboxes_original:
#             start_point = (bbox[0], bbox[1])
#             end_point = (bbox[2], bbox[3])
#             image_original = cv2.rectangle(image_original.copy(), start_point, end_point, (0, 255, 0), 2)
#
#         for kps in keypoints_original:
#             for idx, kp in enumerate(kps):
#                 image_original = cv2.circle(image_original, tuple(kp), 5, (255, 0, 0), 10)
#                 image_original = cv2.putText(image_original, " " + keypoints_classes_ids2names[idx], tuple(kp),
#                                              cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 0, 0), 3, cv2.LINE_AA)
#
#         f, ax = plt.subplots(1, 2, figsize=(40, 20))
#
#         ax[0].imshow(image_original)
#         ax[0].set_title('Original image', fontsize=fontsize)
#
#         ax[1].imshow(image)
#         ax[1].set_title('Transformed image', fontsize=fontsize)
#
#
# image = (batch[0][0].permute(1, 2, 0).numpy() * 255).astype(np.uint8)
# bboxes = batch[1][0]['boxes'].detach().cpu().numpy().astype(np.int32).tolist()
#
# keypoints = []
# for kps in batch[1][0]['keypoints'].detach().cpu().numpy().astype(np.int32).tolist():
#     keypoints.append([kp[:2] for kp in kps])
#
# image_original = (batch[2][0].permute(1, 2, 0).numpy() * 255).astype(np.uint8)
# bboxes_original = batch[3][0]['boxes'].detach().cpu().numpy().astype(np.int32).tolist()
#
# keypoints_original = []
# for kps in batch[3][0]['keypoints'].detach().cpu().numpy().astype(np.int32).tolist():
#     keypoints_original.append([kp[:2] for kp in kps])
#
# visualize(image, bboxes, keypoints, image_original, bboxes_original, keypoints_original)

def get_model(num_keypoints, weights_path=None):
    anchor_generator = AnchorGenerator(sizes=(32, 64, 128, 256, 512),
                                       aspect_ratios=(0.25, 0.5, 0.75, 1.0, 2.0, 3.0, 4.0))
    model = torchvision.models.detection.keypointrcnn_resnet50_fpn(pretrained=False,
                                                                   pretrained_backbone=True,
                                                                   num_keypoints=num_keypoints,
                                                                   num_classes=2,
                                                                   # Background is the first class, object is the second class
                                                                   rpn_anchor_generator=anchor_generator)

    if weights_path:
        state_dict = torch.load(weights_path)
        model.load_state_dict(state_dict)

    return model


device = torch.device('cpu') # torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')

KEYPOINTS_FOLDER_TRAIN = 'glue_tubes_keypoints_dataset_134imgs/train'
KEYPOINTS_FOLDER_TEST = 'glue_tubes_keypoints_dataset_134imgs/test'

dataset_train = ClassDataset(KEYPOINTS_FOLDER_TRAIN, transform=train_transform(), demo=False)
dataset_test = ClassDataset(KEYPOINTS_FOLDER_TEST, transform=None, demo=False)

data_loader_train = DataLoader(dataset_train, batch_size=3, shuffle=True, collate_fn=collate_fn)
data_loader_test = DataLoader(dataset_test, batch_size=1, shuffle=False, collate_fn=collate_fn)

model = get_model(num_keypoints=2)
model.to(device)

params = [p for p in model.parameters() if p.requires_grad]
optimizer = torch.optim.SGD(params, lr=0.001, momentum=0.9, weight_decay=0.0005)
lr_scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.3)
num_epochs = 5

for epoch in range(num_epochs):
    train_one_epoch(model, optimizer, data_loader_train, device, epoch, print_freq=1000)
    lr_scheduler.step()
    evaluate(model, data_loader_test, device)

# Save model weights after training
torch.save(model.state_dict(), 'keypointsrcnn_weights.pth')
