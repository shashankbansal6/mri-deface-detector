import cv2
import numpy as np
import os
import nibabel as nib
import random
import time
from keras import layers, models
from keras import regularizers
import keras.backend as K

from utils import Generator

import argparse

parser = argparse.ArgumentParser()

parser.add_argument("--load_path", required=True, help="Path to npz files using while running load_dataset.py")
parser.add_argument("--input_size", default=32, type=int, help="Input size of images to model")
parser.add_argument("--batch_size", default=16, type=int, help="Batch size while training")
parser.add_argument("--epochs", default=20, type=int, help="Number of epochs")
parser.add_argument("--augment_images", default=False, type=bool, help="Augment images using transformations")
parser.add_argument("--model_path", default="models", help="Model Save Path")
parser.add_argument("--log_path", default="logs", help="Training Log Path")
parser.add_argument("--export_js", default=False, help="Export to TensorflowJS")

args = parser.parse_args()

load_path = args.load_path
input_size = args.input_size
batch_size = args.batch_size
n_epochs = args.epochs
augment = args.augment_images
model_path = args.model_path
log_path = args.log_path

generator = Generator(load_path)

n_train = len(generator.train_files)
n_test = len(generator.test_files)

print('Number of train images :', n_train)
print('Number of test images :', n_test)

# Test to check generator
# generator.test_keras_generator(batch_size=4)

def relu6(x):
    '''Custom activation using relu6'''

    return K.relu(x, max_value=6)


def Conv_BN_RELU(x, filters=32, kernel=3, strides=1, padding='same'):
    '''Helper to create a modular unit containing Convolution, BatchNormalizaton and Activation'''

    x = layers.Conv2D(filters,kernel,strides=strides,padding=padding)(x)
    x = layers.BatchNormalization()(x)
    x = layers.Activation(relu6)(x)
    return x  


def create_submodel():
    '''The feature extracting submodel for which shares parameters'''

    inp = layers.Input(shape=(32,32,1))

    conv1 = Conv_BN_RELU(inp, filters=8, kernel=3, strides=1, padding='same')
    conv1 = Conv_BN_RELU(conv1, filters=8, kernel=3, strides=1, padding='same')
    conv1 = layers.MaxPooling2D()(conv1)

    conv2 = Conv_BN_RELU(conv1, filters=16, kernel=3, strides=1, padding='same')
    conv2 = Conv_BN_RELU(conv2, filters=16, kernel=3, strides=1, padding='same')
    conv2 = layers.MaxPooling2D()(conv2)

    conv3 = Conv_BN_RELU(conv2, filters=32, kernel=3, strides=1, padding='same')
    conv3 = Conv_BN_RELU(conv3, filters=32, kernel=3, strides=1, padding='same')
    conv3 = layers.MaxPooling2D()(conv3)

    out = layers.Flatten()(conv3)

    model = models.Model(inp,out)

    print(model.summary())

    return model


def create_model(input_shape=(32,32)):
    '''Assembles all the submodels into a unified single model'''

    inp1 = layers.Input(shape=(input_shape[0],input_shape[1],1), name='input_1')
    inp2 = layers.Input(shape=(input_shape[0],input_shape[1],1), name='input_2')
    inp3 = layers.Input(shape=(input_shape[0],input_shape[1],1), name='input_3')

    submodel = create_submodel()

    one = submodel(inp1)
    two = submodel(inp2)
    three = submodel(inp3)

    concat = layers.Add()([one,two,three])
    out = layers.Dense(32,activation='sigmoid')(concat)
    dropout = layers.Dropout(0.5)(out)

    out = layers.Dense(1,activation='sigmoid',name='output_node')(dropout)

    return models.Model(inputs=[inp1,inp2,inp3],outputs=out)


# Defining customized metrics
def sensitivity(y_true, y_pred):
    '''Sensitivity = True Positives / (True Positives + False Negatives)'''

    true_positives = K.sum(K.round(K.clip(y_true * y_pred, 0, 1)))
    all_positives = K.sum(K.round(K.clip(y_true, 0, 1)))
    return true_positives / (all_positives + K.epsilon())


def specificity(y_true, y_pred):
    '''Specificity = True Negatives / (True Negatives + False Positives)'''

    true_negatives = K.sum(K.round(K.clip((1-y_true) * (1-y_pred), 0, 1)))
    all_negatives = K.sum(K.round(K.clip(1-y_true, 0, 1)))
    return true_negatives / (all_negatives + K.epsilon())


input_shape = (input_size,input_size)

# Create and compile Keras model
model = create_model(input_shape)
model.compile(loss='binary_crossentropy', optimizer='adam', metrics=['accuracy',sensitivity, specificity])
print(model.summary())

# Create necessary folders for logging and saving
os.makedirs(model_path,exist_ok=True)
os.makedirs(log_path,exist_ok=True)

from keras.callbacks import ModelCheckpoint, CSVLogger

#sizes = [(64,64), (128,128), (196,196), (224,224), (256,256)]
sizes = [input_shape]

train_gen = generator.keras_generator(batch_size=batch_size, train=True, augment=augment, target_size=sizes)
val_gen = generator.keras_generator(batch_size=batch_size, train=False, augment=False, target_size=sizes)

checkpoint = ModelCheckpoint(filepath=os.path.join(model_path, 'model_best.h5'), save_best_only=True, monitor='val_loss',
                             save_weights_only=False)

csv_logger = CSVLogger(os.path.join(log_path, 'training.log'))

# Training with checkpoints for saving and logging results
print('Training the Model...')
model.fit_generator(train_gen, steps_per_epoch=n_train//batch_size,
                    validation_data=val_gen, validation_steps=n_test//batch_size,
                    epochs=n_epochs, callbacks=[checkpoint, csv_logger])


# Save and load model
# model.save('models/model_final_v2.h5')

if args.export_js:

    from keras.models import load_model
    import tensorflowjs as tfjs

    model = load_model(os.path.join(args.model_path, 'model_best.h5'))
    tfjs.converters.save_keras_model(model, os.path.join(models, 'model_js'))

