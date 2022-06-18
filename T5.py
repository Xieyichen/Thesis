# -*- coding: utf-8 -*-
"""Kopie von t5_huggingface_trainer.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1z7yPE_NsqghFCzU0-2uVs9NRhOjdgaJz
"""

"""# **Training**"""

#@title Load Model

model_checkpoint = "t5-small"


from datasets import load_metric

from transformers import AutoTokenizer
    
    
tokenizer = AutoTokenizer.from_pretrained(model_checkpoint)
from transformers import AutoModelForSeq2SeqLM, DataCollatorForSeq2Seq, Seq2SeqTrainingArguments, Seq2SeqTrainer

model = AutoModelForSeq2SeqLM.from_pretrained(model_checkpoint)

#@title Load Data
import pandas as pd

df = pd.read_csv("D:\\Thesis\\data\\1024_characters_pairs.csv", index_col=0)
df = df.drop(columns=["title_length", "abstract_length", "token_len"])

df_train = df[:11864]
df_valid = df[11864:]

from datasets import Dataset
from datasets import load_dataset, load_metric
train_dataset = Dataset.from_pandas(df_train)
valid_dataset = Dataset.from_pandas(df_valid)
metric = load_metric("rouge")

max_input_length = 1024
max_target_length = 512

def preprocess_function(examples):
    inputs = ["headline: " + doc for doc in examples["abstract"]]
    model_inputs = tokenizer(inputs, max_length=max_input_length, truncation=True)

    # Setup the tokenizer for targets
    with tokenizer.as_target_tokenizer():
        labels = tokenizer(examples["title"], max_length=max_target_length, truncation=True)

    model_inputs["labels"] = labels["input_ids"]
    return model_inputs

train_dataset = train_dataset.map(preprocess_function, batched=True)
valid_dataset = valid_dataset.map(preprocess_function, batched=True)

#@title Train Settings
batch_size = 8
model_name = model_checkpoint.split("/")[-1]
args = Seq2SeqTrainingArguments(
    "output/T5/" + f"{model_name}-finetuned-lm_al_paper",
    evaluation_strategy = "epoch",
    learning_rate=3e-4,
    per_device_train_batch_size=batch_size,
    per_device_eval_batch_size=4,
    weight_decay=0.01,
    save_total_limit=2,
    num_train_epochs=3,
    predict_with_generate=True,
    fp16=True,
    push_to_hub=False,
    gradient_accumulation_steps=8,
    save_steps = 500,
    logging_steps = 185,
)
data_collator = DataCollatorForSeq2Seq(tokenizer, model=model)

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
trainer = Seq2SeqTrainer(
    model,
    args,
    train_dataset=train_dataset,
    eval_dataset=valid_dataset,
    data_collator=data_collator,
    tokenizer=tokenizer,
    compute_metrics=compute_metrics
)
old_collator = trainer.data_collator
trainer.data_collator = lambda data: dict(old_collator(data))

trainer.train()

"""# **Generation**"""

model.save_pretrained("./output/T5")

from transformers import AutoModelForSeq2SeqLM, DataCollatorForSeq2Seq, Seq2SeqTrainingArguments, Seq2SeqTrainer

model = AutoModelForSeq2SeqLM.from_pretrained("./output/T5")

import pandas as pd
test_samples = pd.read_csv("path", index_col=0)
test_samples

abstracts = test_samples.abstract.to_list()
titles = test_samples.title.to_list()

def creat_eval_pairs(model, tokenizer, abstracts, titles):
  preds = []
  for abstract, title in zip(abstracts, titles):
    encoding = tokenizer.encode_plus("headline: " + abstract, return_tensors = "pt")
    inputs = encoding["input_ids"].to("cuda")
    attention_masks = encoding["attention_mask"].to("cuda")
    title_ids = model.generate(
            input_ids = inputs,
            attention_mask = attention_masks,
            max_length = 30,
            num_beams = 5,
            num_return_sequences = 5,
            repetition_penalty=2.0, 
            length_penalty=10.0,
            early_stopping = True,
            )
    result = [tokenizer.decode(g, skip_special_tokens=True, clean_up_tokenization_spaces=True) for g in title_ids]
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

import pandas as pd
pred_target_pairs = pd.DataFrame(list(zip(preds, titles)), columns=['predictions', 'targets'])

pred_target_pairs.to_csv("t5-base.csv")