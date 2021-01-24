import collections
import json
import numpy as np
import sys

import openreview_lib as orl

from nltk.corpus import stopwords
from nltk.stem.porter import PorterStemmer
from rank_bm25 import BM25Okapi
from tqdm import tqdm

import openreview_lib as orl


Document = collections.namedtuple("Document",
                                  "key tokens preprocessed_tokens".split())
Result = collections.namedtuple("Result", "queries corpus scores".split())

STEMMER = PorterStemmer()
STOPWORDS = stopwords.words('english')

def preprocess_sentence(sentence_tokens):
  return [STEMMER.stem(word).lower()
      for word in sentence_tokens
      if word.lower() not in STOPWORDS]


def get_top_k_indices(array, k):
  if k > len(array):
    top_k_list = list(enumerate(array))
  else:
    neg_k = 0 - k
    indices = np.argpartition(array, neg_k)[neg_k:]
    top_k_list = [(i, array[i]) for i in indices]
  return list(
      reversed(sorted(
       top_k_list , key=lambda x:x[1])))



def documents_from_chunks(chunks, key_prefix):
  sentences = []
  for chunk in chunks:
    for sentence in chunk:
      if not sentence:
        continue
      sentences.append(sentence)
  documents = []
  for i, sentence in enumerate(sentences):
    key = "_".join([key_prefix, str(i)])
    documents.append(Document(key, sentence,
      preprocess_sentence(sentence)))
  return documents


def get_key_prefix(obj):
  return "_".join([obj["split"], obj["subsplit"]])


def gather_datasets(data_dir):
  corpus_map = {}
  query_map = {}

  for dataset in orl.DATASETS:
    with open(data_dir + dataset + ".json", 'r') as f:
      obj = json.load(f)
    if dataset == orl.Split.UNSTRUCTURED:
      continue
    else:
      key_prefix = get_key_prefix(obj)
      queries = []
      corpus = []
      for pair in obj["review_rebuttal_pairs"]:
        corpus += documents_from_chunks(pair["review_text"], key_prefix +
        "_review_" + str(pair["index"]))
        queries += documents_from_chunks(pair["rebuttal_text"], key_prefix +
        "_rebuttal_" + str(pair["index"]))
      query_map[dataset] = list(sorted(queries, key=lambda x:x.key))
      corpus_map[dataset] = list(sorted(corpus, key=lambda x:x.key))

  assert len(corpus_map) == len(query_map) == 4
  return corpus_map, query_map

PARTITION_K = 20

def score_dataset(corpus, queries):
  model = BM25Okapi([doc.preprocessed_tokens for doc in corpus])
  scores = []
  for query in tqdm(queries):
    query_scores = model.get_scores(query.preprocessed_tokens).tolist()
    scores.append(get_top_k_indices(query_scores, PARTITION_K))
  return scores


def score_datasets_and_write(corpus_map, query_map, data_dir):
  results = {}
  for dataset in orl.DATASETS:
    if dataset == orl.Split.UNSTRUCTURED:
      continue
    else:
      results[dataset] = score_dataset(corpus_map[dataset], query_map[dataset])
  #for dataset, scores in results.items():
  #  with open(data_dir + "/" + dataset +"_scores.json", 'w') as f:
  #    json.dump(scores, f)
  return results


def write_datasets_to_file(corpus_map, query_map, data_dir):
  for dataset, corpus in corpus_map.items():
    queries = query_map[dataset]
    with open(data_dir + "/" + dataset +"_text.json", 'w') as f:
      json.dump({
        "corpus": corpus,
        "queries": queries
        }, f)


def create_example_lines(split, corpus, queries, query_i, doc_1_i, doc_2_i):
  return "".join([
      "\t".join([split,
      " ".join(queries[query_i].tokens),
      " ".join(corpus[doc_1_i].tokens),
      " ".join(corpus[doc_2_i].tokens), "0"]), "\n",
      "\t".join([split,
      " ".join(queries[query_i].tokens),
      " ".join(corpus[doc_2_i].tokens),
      " ".join(corpus[doc_1_i].tokens), "1"]), "\n"])

def create_weak_supervision_tsv(results, data_dir, corpus_map, query_map):
  example_map = {}
  with open(data_dir + "/examples.tsv", 'w') as f:
    for dataset, dataset_results in results.items():
      if dataset == "traindev_train":
        split = 'train'
      elif dataset == "traindev_dev":
        split = 'dev'
      else:
        continue
      example_tuples = []
      corpus = corpus_map[dataset]
      queries = query_map[dataset]
      for query_i, scores in enumerate(tqdm(dataset_results)):
        for j, (doc_1_i, score_1) in enumerate(scores):
          for doc_2_i, score_2 in scores[j+1:]:
            f.write(create_example_lines(split, corpus, queries, query_i, doc_1_i, doc_2_i))


def create_weak_supervision_examples_and_write(results, data_dir):
  example_map = {}
  for dataset, dataset_results in results.items():
    example_tuples = []
    for query_i, scores in enumerate(tqdm(dataset_results)):
      for j, (doc_1_i, score_1) in enumerate(scores):
        for doc_2_i, score_2 in scores[j+1:]:
          if doc_2_i == doc_1_i:
            dsds
          example_tuples.append(Example(query_i, doc_1_i, doc_2_i, 0))
          example_tuples.append(Example(query_i, doc_2_i, doc_1_i, 1))
    with open(data_dir + "/" + dataset +"_examples.json", 'w') as f:
      json.dump(example_tuples, f)
    example_map[dataset] = example_tuples
  return example_map

def mean(l):
  if not l:
    return None
  return sum(l)/len(l)

def mean_reciprocal(l):
  return mean([1/i for i in l])

def calculate_mrr(results, query_map, corpus_map):
  for dataset, dataset_result in results.items():
    queries = query_map[dataset]
    corpus = corpus_map[dataset]
    for query_i, result in enumerate(dataset_result):
      query = queries[query_i]
      search_prefix = "_".join(query.key.replace("rebuttal",
        "review").split("_")[:4])
      relevant_doc_indices = [
          i for i, doc in enumerate(corpus) if doc.key.startswith(search_prefix)
          ]
      ranks = []
      for doc_rank, (doc_idx, score) in enumerate(result):
        if doc_idx in relevant_doc_indices:
          ranks.append(1+doc_rank)
      if not ranks:
        print("\t".join([query.key, "none_retrieved"]))
      else:
        print(
          "\t".join([str(i) for i in [
          query.key, mean_reciprocal(ranks), min(ranks), max(ranks),
          len(ranks) * 100 / len(relevant_doc_indices)
            ]]) )
  

def main():
  data_dir = "../unlabeled/"
  corpus_map, query_map = gather_datasets(data_dir)
  #write_datasets_to_file(corpus_map, query_map, data_dir)
  results = score_datasets_and_write(corpus_map, query_map, data_dir)
  calculate_mrr(results, query_map, corpus_map)
  #examples = create_weak_supervision_tsv(results, data_dir, corpus_map, query_map)
  
if __name__ == "__main__":
  main()
