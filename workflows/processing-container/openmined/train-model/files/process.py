import os
import syft as sy
from syft.grid.public_grid import PublicGridNetwork

import torch as th
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from utils.dataset import OpenminedDataset

# hooking PyTorch
hook = sy.TorchHook(th)

# set parameter
BATCH_SIZE = 256
N_EPOCS = 20
SAVE_MODEL = True
SAVE_MODEL_PATH = '../models'


# Model Architecture
class Net(nn.Module):
    def __init__(self):
        super(Net, self).__init__()
        self.conv1 = nn.Conv2d(1, 20, 5, 1)
        self.conv2 = nn.Conv2d(20, 50, 5, 1)
        self.fc1 = nn.Linear(4*4*50, 500)
        self.fc2 = nn.Linear(500, 10)

    def forward(self, x):
        x = F.relu(self.conv1(x))
        x = F.max_pool2d(x, 2, 2)
        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, 2, 2)
        x = x.view(-1, 4*4*50)
        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        return F.log_softmax(x, dim=1)


device = th.device('cuda:0' if th.cuda.is_available() else 'cpu')
print(f'Using device: {device}')
    
model = Net()
model.to(device)
optimizer = optim.SGD(model.parameters(), lr=0.01)
criterion = nn.CrossEntropyLoss()

# Openmined Grid
grid_addr = 'http://' + os.environ['GRID_HOST'] + ':' + os.environ['GRID_PORT']
grid = PublicGridNetwork(hook, grid_addr)

# Get data references
data = grid.search('#X', '#mnist', '#dataset')
print(f"Data: {data}")
labels = grid.search('#Y', '#mnist', '#dataset')
print(f"Labels: {labels}")

# Get Workers and their locations
workers = {worker : data[worker][0].location for worker in data.keys()}
print(f'Workers: {workers}')

# Dataloader using the pointers-datasets
dataloaders = dict()
for worker in workers.items():
    location = worker[0]
    dataloaders[location] = DataLoader(OpenminedDataset(data[location][0],labels[location][0]),
                                   batch_size=BATCH_SIZE,
                                   shuffle=True,
                                   num_workers=0)
print(f'Dataloaders: {dataloaders}')

def epoch_total_size(data):
    total = 0
    for elem in data:
        total += data[elem][0].shape[0]
#         for i in range(len(data[elem])):
#             total += data[elem][i].shape[0]
    return total


# Training on all nodes
def train(epoch):
    current_epoch_size = 0
    epoch_total = epoch_total_size(data)
    
    ''' iterate over the remote workers - send model to its location '''
    for worker in workers.values():
        model.train()
        model.send(worker)
        current_epoch_size += len(data[worker.id][0])
    
        ''' iterate over batches of remote data '''
        for batch_idx, (imgs, labels) in enumerate(dataloaders[worker.id]):

            ''' forward step '''
            pred = model(imgs)

            ''' compute loss, backprob, update parameter '''
            loss = criterion(pred, labels)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            
        ''' get model and loss back '''
        model.get()
        loss = loss.get()

        print('Train Epoch: {} | With {} data |: [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                  epoch, str(worker.id).upper(), current_epoch_size, epoch_total,
                        100. *  current_epoch_size / epoch_total, loss.item()))

# RUN TRAINING 
print('\n### RUN TRAINING ###')

for epoch in range(N_EPOCS):
    print(f'# Epoch: {epoch}')
    train(epoch)