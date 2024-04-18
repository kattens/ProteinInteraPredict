# -*- coding: utf-8 -*-
"""Pre training bert model on new tokens

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1KX_HqR3QcI_nr_ISokY16bA36_HthxNw

# pretraining the ProtBERT
in this part of the code we want to pretrain a bert model that is already pretrained on single protein inputs. we want the model to learn to understand a pair of protein as part of our input that have the tokens to seperate each protein sequence in the pair.
"""

import pandas as pd
import numpy as np
import torch
import torch

print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CUDA not available")

from google.colab import drive
drive.mount('/content/drive')

pairs_df = pd.read_csv('/content/drive/MyDrive/Pairs_df.csv')

# Truncate each specified column to a maximum length of 500 characters
columns = ['masked_sequence_A', 'masked_sequence_B', 'Sequence_A', 'Sequence_B']
for col in columns:
    pairs_df[col] = pairs_df[col].apply(lambda x: x[:500] if len(x) > 500 else x)

# Find the longest string by length
pairs_df['Length'] = pairs_df['masked_sequence_A'].apply(len)
longest_string = pairs_df.loc[pairs_df['Length'].idxmax(), 'masked_sequence_A']
print(len(longest_string))

pairs_df

"""#changes start form here:
first thing is to update the base model which the tokens are added to.

"""

from transformers import AutoTokenizer, AutoModelForMaskedLM

# Initialize the ProtBERT tokenizer
tokenizer = AutoTokenizer.from_pretrained('Rostlab/prot_bert')

# Define special tokens for entities
special_tokens = ['[ENTITY1]', '[ENTITY2]']

# Add special tokens to the tokenizer
tokenizer.add_special_tokens({'additional_special_tokens': special_tokens})

# Check if the special tokens were added successfully
print(f"Token '[ENTITY1]' has ID: {tokenizer.convert_tokens_to_ids('[ENTITY1]')}")
print(f"Token '[ENTITY2]' has ID: {tokenizer.convert_tokens_to_ids('[ENTITY2]')}")

# Initialize the ProtBERT model configured for Masked Language Modeling
model = AutoModelForMaskedLM.from_pretrained('Rostlab/prot_bert')
model.resize_token_embeddings(len(tokenizer))  # Adjust the model's embedding size to accommodate new tokens
print('Token embeddings resized to accommodate new tokens.')

# Helper function to convert numerical token IDs back to their textual representation
def ids_to_text(ids):
    return ' '.join(tokenizer.convert_ids_to_tokens(ids))

# Check the updated size of the tokenizer's vocabulary
print(f"Updated vocabulary size: {len(tokenizer)}")

if '[ENTITY1]' in tokenizer.get_vocab() and '[ENTITY2]' in tokenizer.get_vocab():
    print("[ENTITY1] and [ENTITY2] are in the tokenizer's vocabulary.")
else:
    print("[ENTITY1] and [ENTITY2] are NOT in the tokenizer's vocabulary.")

vocab = tokenizer.get_vocab()

#just a showcase of all the tokens
vocab

"""#Updated dataset class:
we have added a new parameter to our class called mode so we can tell it to only process the inputs we want.

in this part we only want to work with global input.

in the future we can expand the class and add more properties of the proteins as new input channels
"""

import torch
from torch.utils.data import Dataset
import numpy as np

class ProteinInteractionDataset(Dataset):
    def __init__(self, dataframe, tokenizer, mask_probability=0.15, modes=None):
        """
        Initializes the dataset.

        Args:
            dataframe (pandas.DataFrame): The dataframe containing protein sequences.
            tokenizer (transformers.BertTokenizer): The tokenizer for encoding sequences.
            mask_probability (float): The probability of masking a token for the masked language model.
            modes (list of str): List of modes to prepare data. Options include:
                                 'global_masked' - Returns sequences with random masking.
                                 'local' - Returns non-masked sequences.
                                 Modes can be combined.
        """
        self.dataframe = dataframe
        self.tokenizer = tokenizer
        self.mask_probability = mask_probability
        self.modes = modes if modes else ['global_masked']  # Default to only global_masked if none specified

    def __len__(self):
        return len(self.dataframe)

    def __getitem__(self, idx):
        row = self.dataframe.iloc[idx]
        data = {}

        if 'global_masked' in self.modes:
            global_seq = f"[ENTITY1] {row['Sequence_A']} [SEP] [ENTITY2] {row['Sequence_B']}"
            input_ids, attention_mask, labels = self.random_mask_sequence(global_seq)
            data['input_ids_global_masked'] = input_ids
            data['attention_mask_global_masked'] = attention_mask
            data['labels_global_masked'] = labels

        if 'local' in self.modes:
            local_seq = f"[ENTITY1] {row['Sequence_A']} [SEP] [ENTITY2] {row['Sequence_B']}"
            input_ids, attention_mask = self.tokenize_sequence(local_seq)
            data['input_ids_local'] = input_ids
            data['attention_mask_local'] = attention_mask

        return data

    def tokenize_sequence(self, sequence):
        encoded = self.tokenizer.encode_plus(
            sequence,
            add_special_tokens=True,
            return_tensors='pt',
            padding=False,
            truncation=True
        )
        return encoded['input_ids'].squeeze(0), encoded['attention_mask'].squeeze(0)

    def random_mask_sequence(self, sequence):
        tokens = self.tokenizer.tokenize(sequence)
        input_ids = torch.tensor(self.tokenizer.convert_tokens_to_ids(tokens), dtype=torch.long)
        labels = torch.full(input_ids.shape, -100)  # Use -100 to ignore these indices in loss calculations
        # Decide where to mask tokens
        mask_indices = torch.rand(input_ids.shape) < self.mask_probability
        labels[mask_indices] = input_ids[mask_indices]
        # 80% of the time, replace masked input tokens with tokenizer.mask_token
        actual_mask = mask_indices & (torch.rand(input_ids.shape) < 0.8)
        input_ids[actual_mask] = self.tokenizer.convert_tokens_to_ids([self.tokenizer.mask_token])[0]
        # 10% of the time, replace masked input tokens with a random token
        random_tokens = torch.randint(2, self.tokenizer.vocab_size, input_ids.shape)
        input_ids[mask_indices & ~actual_mask] = random_tokens[mask_indices & ~actual_mask]
        return input_ids, torch.ones_like(input_ids), labels

from torch.nn.utils.rnn import pad_sequence

def collate_fn(batch):
    batched_data = {}
    for mode in ['global_masked', 'local']:
        input_ids = [item.get(f'input_ids_{mode}', torch.Tensor()) for item in batch if f'input_ids_{mode}' in item]
        attention_masks = [item.get(f'attention_mask_{mode}', torch.Tensor()) for item in batch if f'attention_mask_{mode}' in item]
        labels = [item.get(f'labels_{mode}', torch.Tensor()) for item in batch if f'labels_{mode}' in item]

        if input_ids:
            batched_data[f'input_ids_{mode}'] = pad_sequence(input_ids, batch_first=True, padding_value=0)
            batched_data[f'attention_mask_{mode}'] = pad_sequence(attention_masks, batch_first=True, padding_value=0)
            if labels:
                batched_data[f'labels_{mode}'] = pad_sequence(labels, batch_first=True, padding_value=-100)

    return batched_data

# Freeze layers: only train the top 2 layers
for name, param in model.named_parameters():
    if 'encoder.layer' in name:
        layer_index = int(name.split('.')[3])
        param.requires_grad = layer_index >= 10  # Freeze all but the last 2 layers

from torch.utils.data import DataLoader

# Parameters
batch_size = 16
epochs = 3

# Assuming 'df' is your DataFrame containing the protein sequences
dataset = ProteinInteractionDataset(pairs_df, tokenizer, mask_probability=0.15, modes=['global_masked'])
data_loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, collate_fn=collate_fn)

# Calculate total training steps
total_steps = len(data_loader) * epochs

from torch.optim import AdamW

optimizer = AdamW(filter(lambda p: p.requires_grad, model.parameters()), lr=5e-5)

epochs = 3  # Define the number of epochs to train for
for epoch in range(epochs):
    model.train()
    total_loss = 0
    for batch in data_loader:
        input_ids = batch['input_ids_global_masked'].to(device)
        attention_mask = batch['attention_mask_global_masked'].to(device)
        labels = batch['labels_global_masked'].to(device)

        optimizer.zero_grad()
        outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
        loss = outputs.loss
        loss.backward()
        optimizer.step()
        scheduler.step()

        total_loss += loss.item()

    print(f"Epoch {epoch+1}: Loss {total_loss / len(data_loader):.4f}")

    # Save model checkpoint at the end of each epoch
    torch.save({
        'epoch': epoch,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'loss': total_loss / len(data_loader)
    }, f'/content/drive/MyDrive/Checkpoints/checkpoint_epoch_{epoch+1}.pth')

"""#not for here but just remember the loading"""

# Load a checkpoint
checkpoint = torch.load('/content/drive/MyDrive/Checkpoints/checkpoint_epoch_3.pth')
model = BertForMaskedLM.from_pretrained('Rostlab/prot_bert')  # Reinitialize or define a new model
model.resize_token_embeddings(len(tokenizer))
model.load_state_dict(checkpoint['model_state_dict'])
model.to(device)  # Move model to the appropriate device

# Optionally, load the optimizer state if continuing training
optimizer = AdamW(model.parameters(), lr=5e-5)
optimizer.load_state_dict(checkpoint['optimizer_state_dict'])

# Model is now ready to be used for inference or to continue training