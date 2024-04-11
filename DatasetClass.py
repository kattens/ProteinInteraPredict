"""
This block defines a custom dataset class, `ProteinInteractionDataset`, 
for use in machine learning models that process protein sequences. It is built upon PyTorch's 
`Dataset` class and utilizes the BERT tokenizer from the `transformers` library for sequence tokenization. 
The class is initialized with a pandas DataFrame containing protein sequences, a BERT tokenizer, a maximum
 sequence length, and a masking probability for tokens. The dataset supports indexing to retrieve tokenized
   and optionally masked protein sequences, which are prepared in a format suitable for training 
   transformer models. Specifically, it includes methods to tokenize global sequences directly and to 
   both tokenize and apply dynamic masking to local sequences based on a specified probability. 
   The result is a dictionary containing input IDs, attention masks, and labels for local sequences, 
   where labels are used to indicate the original tokens that were masked (facilitating tasks like masked
     language modeling). This setup is particularly designed for tasks that require understanding the 
     interactions between protein sequences through models like BERT, which can benefit from both 
     concatenated sequence inputs and randomly masked training techniques.

"""



import torch
from torch.utils.data import Dataset
from transformers import BertTokenizer
import random



class ProteinInteractionDataset(Dataset):
    def __init__(self, dataframe, tokenizer, max_length=512, mask_probability=0.15):
        """
        Initializes the dataset.
        :param dataframe: Pandas DataFrame containing global and local sequences.
        :param tokenizer: Initialized BertTokenizer for sequence tokenization.
        :param max_length: Maximum sequence length for tokenization.
        :param mask_probability: Probability of masking a token in the local sequences.
        """
        self.dataframe = dataframe
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.mask_probability = mask_probability

    def __len__(self):
        """Returns the total number of items in the dataset."""
        return len(self.dataframe)

    def __getitem__(self, idx):
        """
        Retrieves an item by index.
        :param idx: Index of the item.
        :return: A dictionary containing tokenized inputs for global sequences, and
                 tokenized and dynamically masked inputs along with labels for local sequences.
        """
        row = self.dataframe.iloc[idx]
        # Tokenize and concatenate global sequences
        global_seq = f"[ENTITY1] {row['Sequence_A']} [SEP] [ENTITY2] {row['Sequence_B']}"
        local_seq = f"[ENTITY1] {row['masked_sequence_A']} [SEP] [ENTITY2] {row['masked_sequence_B']}"
   
        input_ids_global, attention_mask_global = self.tokenize_sequence(global_seq)
        input_ids_local, attention_mask_local, labels_local = self.mask_and_tokenize_sequence(local_seq)


        return {
            "input_ids_global": input_ids_global,
            "attention_mask_global": attention_mask_global,
            "input_ids_local": input_ids_local,
            "attention_mask_local": attention_mask_local,
            "labels_local": labels_local,
        }

    def tokenize_sequence(self, sequence):
        """
        Tokenizes a sequence, respecting the max_length constraint.
        """
        encoded = self.tokenizer.encode_plus(
            sequence,
            add_special_tokens=True,
            max_length=self.max_length,
            padding='max_length',
            truncation=True,
            return_tensors='pt'
        )
        return encoded['input_ids'].squeeze(0), encoded['attention_mask'].squeeze(0)



    def mask_and_tokenize_sequence(self, sequence):
        """
        Masks tokens in a sequence with a specified probability and tokenizes the sequence.
        """
        tokens = self.tokenizer.tokenize(sequence)
        masked_tokens, labels = [], []

        for token in tokens:
            if random.random() < self.mask_probability:
                masked_tokens.append(self.tokenizer.mask_token)
                labels.append(self.tokenizer.convert_tokens_to_ids(token))
            else:
                masked_tokens.append(token)
                labels.append(-100)  # -100 is used to ignore these tokens in loss calculation

        # Convert list of tokens to IDs and truncate or pad as necessary
        encoded = self.tokenizer(
            masked_tokens, max_length=self.max_length, padding='max_length',
            truncation=True, is_split_into_words=True, return_tensors='pt'
        )
        input_ids = encoded['input_ids'].squeeze(0)
        attention_mask = encoded['attention_mask'].squeeze(0)
        labels += [-100] * (self.max_length - len(labels))

        return input_ids, attention_mask, torch.tensor(labels, dtype=torch.long)
    



    """
    This is the collate func for handling the len of the sequences when doing batch processing
    """

def collate_fn(batch):
    # Determine the maximum length in this batch for dynamic padding
    # We calculate max length considering both global and local input IDs
    max_length = max(max(len(item['input_ids_global']), len(item['input_ids_local'])) for item in batch)
    
    # Initialize a dictionary to hold the padded versions of our batch data
    padded_batch = {}

    # Iterate over each key in the items of the batch; these keys represent different tensor types
    for key in ['input_ids_global', 'attention_mask_global', 'labels_global', 'input_ids_local', 'attention_mask_local']:
        # Create a padded version of each tensor type in the batch
        padded_vector = [
            torch.cat([item[key],  # Original tensor
                       torch.full((max_length - len(item[key]),),  # Padding to max length
                                  fill_value=0 if 'mask' in key or 'input_ids' in key else -100)])  # Padding value
            for item in batch  # For each item in the batch
        ]

        # Convert the list of tensors to a single tensor
        padded_batch[key] = torch.stack(padded_vector)

    # Return the padded batch, which now contains tensors of equal length
    return padded_batch
