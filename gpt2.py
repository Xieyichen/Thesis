# -*- coding: utf-8 -*-
"""GPT2.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/10iqJnPBp3B4NU5a_cU5r_K4KEcST4dj2
"""

"""# **Training**"""

#@title Load Model
model_checkpoint = "gpt2"

from datasets import load_metric

from transformers import GPT2LMHeadModel, DataCollatorForLanguageModeling, TrainingArguments, Trainer

model = GPT2LMHeadModel.from_pretrained(model_checkpoint)
from transformers import GPT2Tokenizer
    
def load_tokenizer():
    tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
    special_tokens = {'bos_token':'<|startoftext|>','eos_token':'<|endoftext|>','pad_token':'<pad>','additional_special_tokens':['<TITLE>']} 
    tokenizer.add_special_tokens(special_tokens)
    return tokenizer

tokenizer = load_tokenizer()
model.resize_token_embeddings(len(tokenizer))

#@title Load Data
import pandas as pd
df = pd.read_csv("D:\\Thesis\\data\\1024_characters_pairs.csv", index_col=0)

df = df.drop(columns=["title_length", "abstract_length", "token_len"])
df_train = df[:11864]
df_valid = df[11864:]
def add_input(df):
  inputs = []
  for a,t in zip(df.abstract.to_list(), df.title.to_list()):
    input = a + "<TITLE>" + t + "<|endoftext|>"
    inputs.append(input)
  df["input"] = inputs
  return df
df_train = add_input(df_train)
df_valid = add_input(df_valid)
df_train = df_train.drop(columns=["title", "abstract"])
df_valid = df_valid.drop(columns=["title", "abstract"])
from datasets import Dataset
from datasets import load_dataset, load_metric
train_dataset = Dataset.from_pandas(df_train)
valid_dataset = Dataset.from_pandas(df_valid)
metric = load_metric("rouge")

max_input_length = 620
def preprocess_function(examples):
    model_inputs = tokenizer(examples["input"], padding="max_length", max_length=max_input_length, truncation=True)

    # Setup the tokenizer for targets
    labels = model_inputs

    model_inputs["labels"] = labels["input_ids"]
    return model_inputs

train_dataset = train_dataset.map(preprocess_function, batched=True)
valid_dataset = valid_dataset.map(preprocess_function, batched=True)

from operator import indexOf
def get_max_len(train_dataset, valid_dataset, max_global_input_len):
  for i in train_dataset:
    t = indexOf(i["input_ids"], tokenizer.eos_token_id) + 1
    if t > max_global_input_len:
      max_global_input_len = t

  for i in valid_dataset:
    t = indexOf(i["input_ids"], tokenizer.eos_token_id) + 1
    if t > max_global_input_len:
      max_global_input_len = t
  return max_global_input_len

max_global_input_len = get_max_len(train_dataset, valid_dataset, 0)

#@title Training Settings
batch_size = 2
model_name = model_checkpoint.split("/")[-1]
args = TrainingArguments(
    "output/gpt2/" + f"{model_name}-finetuned-lm_al_paper",
    evaluation_strategy = "epoch",
    learning_rate=3e-4,
    per_device_train_batch_size=batch_size,
    per_device_eval_batch_size=1,
    weight_decay=0.01,
    save_total_limit=2,
    num_train_epochs=3,
    fp16=True,
    push_to_hub=False,
    gradient_accumulation_steps=8,
    save_steps = 200,
    logging_steps = 185,
)
data_collator = DataCollatorForLanguageModeling(tokenizer, mlm=False)

#@title Load ROUGE
import nltk
import numpy as np
nltk.download('punkt')
def compute_metrics(eval_pred):
    predictions, labels = eval_pred
    decoded_preds = tokenizer.batch_decode(predictions, skip_special_tokens=True)
    # Replace -100 in the labels as we can't decode them.
    labels = np.where(labels != -100, labels, tokenizer.pad_token_id)
    decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)
    
    # Rouge expects a newline after each sentence
    decoded_preds = ["\n".join(nltk.sent_tokenize(pred.strip())) for pred in decoded_preds]
    decoded_labels = ["\n".join(nltk.sent_tokenize(label.strip())) for label in decoded_labels]
    
    result = metric.compute(predictions=decoded_preds, references=decoded_labels, use_stemmer=True)
    # Extract a few results
    result = {key: value.mid.fmeasure * 100 for key, value in result.items()}
    
    # Add mean generated length
    prediction_lens = [np.count_nonzero(pred != tokenizer.pad_token_id) for pred in predictions]
    result["gen_len"] = np.mean(prediction_lens)
    
    return {k: round(v, 4) for k, v in result.items()}

#@title Trainer Settings
trainer = Trainer(
    model,
    args,
    train_dataset=train_dataset,
    eval_dataset=valid_dataset,
    data_collator=data_collator,
    tokenizer=tokenizer,
    #compute_metrics=compute_metrics
)
old_collator = trainer.data_collator

trainer.data_collator = lambda data: dict(old_collator(data))

trainer.train()

model.save_pretrained("./output/gpt2")

"""# **Generation**"""

import pandas as pd
test_samples = pd.read_csv("/content/drive/MyDrive/Thesis/data/1024_length_data/test_pairs.csv", index_col=0)
test_samples

test_samples["token_len"] = test_samples["abstract"].apply(lambda s: len('<pad>' + s + '</s>'))
test_samples = test_samples[test_samples.token_len < 1024]
test_samples

abstracts = test_samples.abstract.to_list()
titles = test_samples.title.to_list()

def creat_eval_pairs(model, tokenizer, abstracts, titles):
  preds = []
  for abstract, title in zip(abstracts, titles):
    encoding = tokenizer(abstract + "<TITLE>", return_tensors = "pt", max_length=620)
    inputs = encoding["input_ids"].to("cuda")
    attention_masks = encoding["attention_mask"].to("cuda")
    title_ids = model.generate(
            input_ids = inputs,
            attention_mask = attention_masks,
            max_length = 1024,
            num_beams = 5,
            num_return_sequences = 5,
            repetition_penalty=2.0, 
            length_penalty=10.0,
            early_stopping = True,
            )
    result = []
    for g in title_ids:
      result.append(tokenizer.decode(g).split("<TITLE>")[1].split("<|endoftext|>")[0])
    s=""
    for t in result:
      s = s + "<TITLE>" + t
    preds.append(s)
    if len(preds) % 500 == 0:
      print("original title: ", title)
      print("generated title: ", preds[-1:])
  return preds, titles

model.to("cuda")

preds, titles = creat_eval_pairs(model, tokenizer, abstracts, titles)

pred_target_pairs = pd.DataFrame(list(zip(preds, titles)), columns=['predictions', 'targets'])

pred_target_pairs.to_csv("/content/drive/MyDrive/Thesis/output/preds_targets_pairs/gpt2.csv")