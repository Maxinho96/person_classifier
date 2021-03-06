from absl import app, flags
from absl.flags import FLAGS

import tensorflow as tf
import tensorflow.keras as keras
import numpy as np
import matplotlib.pyplot as plt

import os
from functools import partial


flags.DEFINE_string("dataset",
                    "data/casia_gait/DatasetB_split_reduced",
                    "Path to dataset")
flags.DEFINE_string("class_names_file",
                    "class_names.txt",
                    "Class names txt file (must be in dataset directory)")
# Data augmentation flags
flags.DEFINE_boolean("random_flip",
                     True,
                     "Use or not random flip data augmentation")
flags.DEFINE_boolean("random_hue",
                     True,
                     "Use or not random hue data augmentation")
flags.DEFINE_boolean("random_saturation",
                     True,
                     "Use or not random saturation data augmentation")
flags.DEFINE_boolean("random_contrast",
                     True,
                     "Use or not random contrast data augmentation")
flags.DEFINE_boolean("random_brightness",
                     True,
                     "Use or not random brightness data augmentation")


def preprocess(image, label, size):
    # Resize the image to the desired size.
    if size is not None:
        image = tf.image.resize_with_pad(image, size, size)
    # Convert uint8 image to float32 image
    image = tf.cast(image, tf.float32)
    # Preprocess input for Xception
    # (this wants an RGB float image in range [0., 255.], and gives
    # an RGB float image in range [-1., 1.]
    image = keras.applications.xception.preprocess_input(image)

    return image, label


def augment(image, label):
    # Randomly flip the image horizontally.
    if FLAGS.random_flip:
        image = tf.image.random_flip_left_right(image)
    # Randomly adjust the image hue.
    if FLAGS.random_hue:
        image = tf.image.random_hue(image, 0.2)
    # Randomly adjust the image saturation.
    if FLAGS.random_saturation:
        image = tf.image.random_saturation(image, 0, 1.25)
    # Randomly adjust the image contrast.
    if FLAGS.random_contrast:
        image = tf.image.random_contrast(image, 0.85, 3.5)
    # Randomly adjust the image brightness.
    if FLAGS.random_brightness:
        image = tf.image.random_brightness(image, 0.075)

    return image, label


def decode_image(file_path, class_names):
    # Convert the path to a list of path components
    parts = tf.strings.split(file_path, os.path.sep)
    # The second to last is the class-directory
    label = parts[-2] == class_names
    # Load the raw data from the file as a string
    image = tf.io.read_file(file_path)
    # Convert the compressed string to a 3D uint8 tensor
    image = tf.image.decode_jpeg(image, channels=3)

    return image, label


# Returns the dataset split indicated in the split parameter.
# If size is None, images are not resized and dynamic batches are created.
def load(split="train",
         size=None,
         batch_size=8,
         cache=True):
    if split in os.listdir(FLAGS.dataset):
        AUTOTUNE = tf.data.experimental.AUTOTUNE

        dataset_dir = os.path.join(FLAGS.dataset, split)

        class_names_path = os.path.join(FLAGS.dataset, FLAGS.class_names_file)

        with open(class_names_path, "r") as class_names_file:
            class_names = class_names_file.read().splitlines()

        # Load files.
        pattern = [os.path.join(dataset_dir, c, "*") for c in class_names]
        filenames_ds = tf.data.Dataset.list_files(pattern)

        dataset_length = tf.data.experimental.cardinality(filenames_ds).numpy()

        # Decode images and add labels.
        decode_fn = partial(decode_image,
                            class_names=class_names)
        labeled_ds = filenames_ds.map(decode_fn,
                                      num_parallel_calls=AUTOTUNE)

        # Cache the dataset if fits in memory.
        if cache:
            labeled_ds = labeled_ds.cache()

        if split == "train":
            # Do data augmentation on the training set.
            labeled_ds = labeled_ds.map(augment,
                                        num_parallel_calls=AUTOTUNE)
        if split != "test":
            # Shuffle the training and validation set.
            labeled_ds = labeled_ds.shuffle(buffer_size=1000)
            # Repeat the training and validation set undefinitely.
            labeled_ds = labeled_ds.repeat()

        preprocess_fn = partial(preprocess, size=size)
        if size is None:
            # Create batches using buckets: images with similar height will
            # be in the same batch. Minimum extra padding is added if needed.
            # Buckets are intervals of 10 pixels, from 60 to 200.
            bucket_boundaries = list(range(70, 221, 10))
            bucket_batch_sizes = [batch_size] * (len(bucket_boundaries) + 1)
            labeled_ds = labeled_ds.apply(
                tf.data.experimental.bucket_by_sequence_length(
                    # Use the height of the images to choose the bucket.
                    element_length_func=lambda image, label: \
                    tf.shape(image)[0],
                    bucket_boundaries=bucket_boundaries,
                    bucket_batch_sizes=bucket_batch_sizes,
                    padding_values=(
                        # Padding value for images.
                        tf.constant(0, dtype="uint8"),
                        # Padding value for labels.
                        False)
                )
            )
            labeled_ds = labeled_ds.map(preprocess_fn,
                                        num_parallel_calls=AUTOTUNE)
        else:
            labeled_ds = labeled_ds.map(preprocess_fn,
                                        num_parallel_calls=AUTOTUNE)
            labeled_ds = labeled_ds.batch(batch_size)

        # Remove images with size < 71 (Not supported by Xception).
        labeled_ds = labeled_ds.filter(lambda batch, labels:
                                       tf.shape(batch)[1] > 70 and
                                       tf.shape(batch)[2] > 70)

        labeled_ds = labeled_ds.apply(
            tf.data.experimental.copy_to_device("/gpu:0"))
        # Preload the next batch while the current batch is on GPU.
        labeled_ds = labeled_ds.prefetch(buffer_size=AUTOTUNE)

        return labeled_ds, np.array(class_names), dataset_length

    else:
        print("Cannot load {} split, directory not found!".format(split))


def show_batch(image_batch, label_batch, class_names):
    plt.figure(figsize=(10, 10))
    batch_size = image_batch.shape[0]
    for n in range(batch_size):
        _ = plt.subplot(1, batch_size, n + 1)
        image = image_batch[n]
        plt.imshow(image / 2 + 0.5)
        plt.title(class_names[label_batch[n]][0]+"\n"+str(image.shape))
        plt.axis('off')
    plt.show()


def main(_argv):
    train_set, class_names, length = load(split="train",
                                          size=None,
                                          batch_size=8,
                                          cache=True)

    for image_batch, label_batch in train_set:
        show_batch(image_batch.numpy(),
                   label_batch.numpy(),
                   class_names)
        if input() == "q":
            break


if __name__ == "__main__":
    app.run(main)
