You are the repair agent of a reproducibility audit of a machine-learning paper. The paper's code is in the
directory `./repo` (relative to your working directory): the code as shipped, plus the audit's changes so far.
Read it with Read, Grep and Glob.

The audit runs the code as the authors shipped it and may change it only to make it RUN. It must never change WHAT IS
MEASURED.
- Allowed, class `env`: environment fixes, such as an absolute path from the authors' machine, GPU-only device
  selection on a machine without a GPU, a missing import.
- Allowed, class `compat`: compatibility fixes, such as a call into a library API that no longer exists, on a code
  path the experiment does not use.
- Not a repair, class `hypothesis`: any change to data, splits, domains or data generation, to the model, loss,
  optimizer, metric or model selection, or to any number used in training.
Your class is advisory: the audit's code decides the class from the patch.

The audited run is CPU only. The command, run from the repository root:
    python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 1 --method_name erm_match --match_case 0.0 --penalty_ws 0.0

It failed. Failure class (assigned by code): no GPU (CUDA / NVIDIA driver message).

Traceback (repository paths are relative to the repository root):
```
Traceback (most recent call last):
  File "train.py", line 227, in <module>
    train_method= ErmMatch(
  File "algorithms/erm_match.py", line 24, in __init__
    super().__init__(args, train_dataset, val_dataset, test_dataset, base_res_dir, post_string, cuda) 
  File "algorithms/algo.py", line 100, in __init__
    self.phi= self.get_model()
  File "algorithms/algo.py", line 170, in get_model
    phi=phi.to(self.cuda)
  File "<env>/lib/python3.9/site-packages/torch/nn/modules/module.py", line 907, in to
    return self._apply(convert)
  File "<env>/lib/python3.9/site-packages/torch/nn/modules/module.py", line 578, in _apply
    module._apply(fn)
  File "<env>/lib/python3.9/site-packages/torch/nn/modules/module.py", line 578, in _apply
    module._apply(fn)
  File "<env>/lib/python3.9/site-packages/torch/nn/modules/module.py", line 601, in _apply
    param_applied = fn(param)
  File "<env>/lib/python3.9/site-packages/torch/nn/modules/module.py", line 905, in convert
    return t.to(device, dtype if t.is_floating_point() or t.is_complex() else None, non_blocking)
  File "<env>/lib/python3.9/site-packages/torch/cuda/__init__.py", line 210, in _lazy_init
    raise AssertionError("Torch not compiled with CUDA enabled")
AssertionError: Torch not compiled with CUDA enabled
```

Source around each repository frame of the traceback (line numbers on the left):
--- train.py:227 (lines 187-267) ---
```
  187  if args.dp_noise:
  188      base_res_dir=(
  189                  res_dir + args.dataset_name + '/' + 'dp_' +  str(args.dp_epsilon) + '_' + args.method_name + '/' + args.match_layer 
  190                  + '/' + 'train_' + str(args.train_domains)
  191              )    
  192  else:
  193      base_res_dir=(
  194                  res_dir + args.dataset_name + '/' + args.method_name + '/' + args.match_layer 
  195                  + '/' + 'train_' + str(args.train_domains)
  196              )
  197  
  198  #TODO: Handle slab noise case in helper functions
  199  if args.dataset_name == 'slab':
  200      base_res_dir= base_res_dir + '/slab_noise_'  + str(args.slab_noise)
  201      
  202  if not os.path.exists(base_res_dir):
  203      os.makedirs(base_res_dir)    
  204  
  205  #Execute the method for multiple runs ( total args.n_runs )
  206  for run in range(args.n_runs):
  207      print('Run', run)
  208      #Seed for repoduability
  209      random.seed(run*10)
  210      np.random.seed(run*10) 
  211      torch.manual_seed(run*10)    
  212      if torch.cuda.is_available():
  213          torch.cuda.manual_seed_all(run*10)    
  214              
  215      #DataLoader        
  216      train_dataset= get_dataloader( args, run, train_domains, 'train', 0, kwargs )    
  217      if args.method_name == 'matchdg_ctr':
  218          val_dataset= get_dataloader( args, run, train_domains, 'val', 1, kwargs )            
  219      else:
  220          val_dataset= get_dataloader( args, run, train_domains, 'val', 0, kwargs )    
  221      test_dataset= get_dataloader( args, run, test_domains, 'test', 0, kwargs )    
  222  #     print('Train Domains, Domain Size, BaseDomainIdx, Total Domains: ', train_domains, total_domains, domain_size, training_list_size)
  223      
  224      #Import the module as per the current training method
  225      if args.method_name == 'erm_match' or args.method_name == 'mask_linear' or args.method_name == 'dp_erm':
  226          from algorithms.erm_match import ErmMatch    
  227>         train_method= ErmMatch(
  228                                  args, train_dataset, val_dataset,
  229                                  test_dataset, base_res_dir, 
  230                                  run, cuda
  231                                )
  232      elif args.method_name == 'matchdg_ctr':
  233          from algorithms.match_dg import MatchDG
  234          ctr_phase=1
  235          train_method= MatchDG(
  236                                  args, train_dataset, val_dataset,
  237                                  test_dataset, base_res_dir, 
  238                                  run, cuda, ctr_phase
  239                               )     
  240      elif args.method_name == 'matchdg_erm':
  241          from algorithms.match_dg import MatchDG
  242          ctr_phase=0
  243          train_method= MatchDG(
  244                                  args, train_dataset, val_dataset,
  245                                  test_dataset, base_res_dir,
  246                                  run, cuda, ctr_phase
  247                               )
  248      elif args.method_name == 'hybrid':
  249          from algorithms.hybrid import Hybrid
  250          train_method= Hybrid(
  251                                  args, train_dataset, val_dataset,
  252                                  test_dataset, base_res_dir,
  253                                  run, cuda
  254                               )        
  255      elif args.method_name == 'erm':
  256          from algorithms.erm import Erm    
  257          train_method= Erm(
  258                                  args, train_dataset, val_dataset,
  259                                  test_dataset, base_res_dir, 
  260                                  run, cuda
  261                                )           
  262      elif args.method_name == 'irm':
  263          from algorithms.irm import Irm    
  264          train_method= Irm(
  265                                  args, train_dataset, val_dataset,
  266                                  test_dataset, base_res_dir, 
  267                                  run, cuda
```

--- algorithms/erm_match.py:24 (lines 1-64) ---
```
    1  import sys
    2  import numpy as np
    3  import argparse
    4  import copy
    5  import random
    6  import json
    7  import time
    8  
    9  import torch
   10  from torch.autograd import grad
   11  from torch import nn, optim
   12  from torch.nn import functional as F
   13  from torchvision import datasets, transforms
   14  from torchvision.utils import save_image
   15  from torch.autograd import Variable
   16  import torch.utils.data as data_utils
   17  
   18  from .algo import BaseAlgo
   19  from utils.helper import l1_dist, l2_dist, embedding_dist, cosine_similarity
   20  
   21  class ErmMatch(BaseAlgo):
   22      def __init__(self, args, train_dataset, val_dataset, test_dataset, base_res_dir, post_string, cuda):
   23          
   24>         super().__init__(args, train_dataset, val_dataset, test_dataset, base_res_dir, post_string, cuda) 
   25  
   26                  
   27      def train(self):
   28          
   29          self.max_epoch= -1
   30          self.max_val_acc= 0.0
   31          for epoch in range(self.args.epochs):   
   32              
   33              if epoch ==0:
   34                  inferred_match= 0
   35                  self.data_matched, self.domain_data= self.get_match_function(inferred_match, self.phi)                
   36              elif epoch % self.args.match_interrupt == 0 and self.args.match_flag:
   37                  inferred_match= 1
   38                  self.data_matched, self.domain_data= self.get_match_function(inferred_match, self.phi)
   39          
   40              penalty_erm=0
   41              penalty_ws=0
   42              train_acc= 0.0
   43              train_size=0
   44              
   45              total_grad_norm= []
   46              
   47              #Batch iteration over single epoch
   48              for batch_idx, (x_e, y_e ,d_e, idx_e, obj_e) in enumerate(self.train_dataset):
   49                  
   50  #                 self.opt.zero_grad()
   51                  loss_e= torch.tensor(0.0).to(self.cuda)
   52                  
   53                  x_e= x_e.to(self.cuda)
   54                  y_e= torch.argmax(y_e, dim=1).to(self.cuda)
   55                  d_e= torch.argmax(d_e, dim=1).numpy()
   56                  
   57  
   58                  wasserstein_loss=torch.tensor(0.0).to(self.cuda)
   59                  erm_loss= torch.tensor(0.0).to(self.cuda) 
   60                  if epoch > self.args.penalty_s:
   61                      # To cover the varying size of the last batch for data_match_tensor_split, label_match_tensor_split
   62                      total_batch_size= len(self.data_matched)
   63                      if batch_idx >= total_batch_size:
   64                          break
```

--- algorithms/algo.py:100 (lines 60-140) ---
```
   60              raise ValueError("The privacy budget is too low.")
   61  
   62      while sigma_max - sigma_min > 0.01:
   63          sigma = (sigma_min + sigma_max) / 2
   64          rdp = privacy_analysis.compute_rdp(
   65              sample_rate, sigma, epochs / sample_rate, alphas
   66          )
   67          eps = privacy_analysis.get_privacy_spent(alphas, rdp, target_delta)[0]
   68  
   69          if eps < target_epsilon:
   70              sigma_max = sigma
   71          else:
   72              sigma_min = sigma
   73  
   74      return sigma
   75  
   76  
   77  class BaseAlgo():
   78      def __init__(self, args, train_dataset, val_dataset, test_dataset, base_res_dir, run, cuda):
   79          
   80          
   81          self.args= args
   82          self.train_dataset= train_dataset['data_loader']
   83          if args.method_name == 'matchdg_ctr':
   84              self.val_dataset= val_dataset
   85          else:
   86              self.val_dataset= val_dataset['data_loader']
   87          self.test_dataset= test_dataset['data_loader']
   88          
   89          self.train_domains= train_dataset['domain_list']
   90          self.total_domains= train_dataset['total_domains']
   91          self.domain_size= train_dataset['base_domain_size'] 
   92          self.training_list_size= train_dataset['domain_size_list']
   93          
   94          self.base_res_dir= base_res_dir
   95          self.run= run
   96          self.cuda= cuda
   97          
   98          self.post_string= str(self.args.penalty_ws) + '_' + str(self.args.penalty_diff_ctr) + '_' + str(self.args.match_case) + '_' + str(self.args.match_interrupt) + '_' + str(self.args.match_flag) + '_' + str(self.run) + '_' + self.args.pos_metric + '_' + self.args.model_name
   99          
  100>         self.phi= self.get_model()
  101          self.opt= self.get_opt()
  102          self.scheduler = torch.optim.lr_scheduler.StepLR(self.opt, step_size=25)    
  103          
  104          self.final_acc=[]
  105          self.val_acc=[]
  106          self.train_acc=[]
  107          
  108          # Differentially Private Noise
  109          if self.args.dp_noise:
  110              self.privacy_engine= self.get_dp_noise()
  111      
  112      def get_model(self):
  113          
  114          if self.args.model_name == 'lenet':
  115              from models.lenet import LeNet5
  116              phi= LeNet5()
  117  
  118          if self.args.model_name == 'slab':
  119              from models.slab import SlabClf
  120              if self.args.method_name in ['csd', 'matchdg_ctr']:
  121                  fc_layer=0
  122              else:
  123                  fc_layer= self.args.fc_layer
  124              phi= SlabClf(self.args.slab_data_dim, self.args.out_classes, fc_layer)
  125              
  126          if self.args.model_name == 'fc':
  127              from models.fc import FC
  128              if self.args.method_name in ['csd', 'matchdg_ctr']:
  129                  fc_layer=0
  130              else:
  131                  fc_layer= self.args.fc_layer
  132              phi= FC(self.args.out_classes, fc_layer)
  133              
  134          if self.args.model_name == 'domain_bed_mnist':
  135              from models.domain_bed_mnist import DomainBed
  136              if self.args.method_name in ['csd', 'matchdg_ctr']:
  137                  fc_layer=0
  138              else:
  139                  fc_layer= self.args.fc_layer                        
  140              phi= DomainBed(self.args.img_c, fc_layer)
```

--- algorithms/algo.py:170 (lines 130-210) ---
```
  130              else:
  131                  fc_layer= self.args.fc_layer
  132              phi= FC(self.args.out_classes, fc_layer)
  133              
  134          if self.args.model_name == 'domain_bed_mnist':
  135              from models.domain_bed_mnist import DomainBed
  136              if self.args.method_name in ['csd', 'matchdg_ctr']:
  137                  fc_layer=0
  138              else:
  139                  fc_layer= self.args.fc_layer                        
  140              phi= DomainBed(self.args.img_c, fc_layer)
  141              
  142          if self.args.model_name == 'alexnet':
  143              from models.alexnet import alexnet
  144              if self.args.method_name in ['csd', 'matchdg_ctr']:
  145                  fc_layer=0
  146              else:
  147                  fc_layer= self.args.fc_layer            
  148              phi= alexnet(self.args.model_name, self.args.out_classes, fc_layer, 
  149                              self.args.img_c, self.args.pre_trained, self.args.os_env)
  150              
  151          if 'resnet' in self.args.model_name:
  152              from models.resnet import get_resnet
  153              if self.args.method_name in ['csd', 'matchdg_ctr']:
  154                  fc_layer=0
  155              else:
  156                  fc_layer= self.args.fc_layer
  157              phi= get_resnet(self.args.model_name, self.args.out_classes, fc_layer, 
  158                              self.args.img_c, self.args.pre_trained, self.args.dp_noise, self.args.os_env)
  159              
  160          if 'densenet' in self.args.model_name:
  161              from models.densenet import get_densenet
  162              if self.args.method_name in ['csd', 'matchdg_ctr']:
  163                  fc_layer=0
  164              else:
  165                  fc_layer= self.args.fc_layer
  166              phi= get_densenet(self.args.model_name, self.args.out_classes, fc_layer, 
  167                              self.args.img_c, self.args.pre_trained, self.args.os_env)
  168              
  169          print('Model Architecture: ', self.args.model_name)
  170>         phi=phi.to(self.cuda)
  171          return phi
  172      
  173      def save_model(self):
  174          # Store the weights of the model
  175          torch.save(self.phi.state_dict(), self.base_res_dir + '/Model_' + self.post_string + '.pth')
  176          
  177          # Store the validation, test loss over the training epochs
  178          np.save( self.base_res_dir + '/Val_Acc_' + self.post_string + '.npy', np.array(self.val_acc) )
  179          np.save( self.base_res_dir + '/Test_Acc_' + self.post_string + '.npy', np.array(self.final_acc))
  180      
  181      def get_opt(self):
  182          if self.args.opt == 'sgd':
  183              opt= optim.SGD([
  184                           {'params': filter(lambda p: p.requires_grad, self.phi.parameters()) }, 
  185                  ], lr= self.args.lr, weight_decay= self.args.weight_decay, momentum= 0.9,  nesterov=True )        
  186          elif self.args.opt == 'adam':
  187              opt= optim.Adam([
  188                          {'params': filter(lambda p: p.requires_grad, self.phi.parameters())},
  189                  ], lr= self.args.lr)
  190          
  191          return opt
  192  
  193      
  194      def get_match_function(self, inferred_match, phi):
  195          
  196          data_matched, domain_data, _= get_matched_pairs( self.args, self.cuda, self.train_dataset, self.domain_size, self.total_domains, self.training_list_size, phi, self.args.match_case, self.args.perfect_match, inferred_match )
  197                  
  198  #         #Start initially with randomly defined batch; else find the local approximate batch
  199  #         if epoch > 0:                    
  200  #             inferred_match=1
  201  #             if self.args.match_flag:
  202  #                 data_matched, domain_data, _= get_matched_pairs( self.args, self.cuda, self.train_dataset, self.domain_size, self.total_domains, self.training_list_size, self.phi, self.args.match_case, perfect_match, inferred_match )
  203  #             else:
  204  #                 temp_1, temp_2, _= get_matched_pairs( self.args, self.cuda, self.train_dataset, self.domain_size, self.total_domains, self.training_list_size, self.phi, self.args.match_case, perfect_match, inferred_match )                
  205  #         else:
  206  #             inferred_match=0
  207  #             data_matched, domain_data, _= get_matched_pairs( self.args, self.cuda, self.train_dataset, self.domain_size, self.total_domains, self.training_list_size, self.phi, self.args.match_case, perfect_match, inferred_match )
  208          
  209          
  210          # Randomly Shuffle the list of matched data indices and divide as per batch sizes
```

Scripts this audit runs (entry points): data_gen_syn.py, train.py, test.py.

Write the smallest patch that makes this failure go away without changing what is measured:
- Fix the root cause where the faulty value or call is written, which may be far from where it is used; read the
  repository to find it.
- If the same defect is written elsewhere in the code this audit runs (the entry points below and the repository
  modules they import), fix every occurrence in this one patch. Leave every other file unchanged, including scripts
  the audit does not run.
- Do not touch anything the failure does not need.

Answer with `edits`: each edit names a `file` (relative to the repository root), gives `old` (exact current text of
one or more whole lines, appearing exactly once in that file, indentation included) and `new` (the replacement
lines). Also give your `class` and a one-sentence `rationale`.
