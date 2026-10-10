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

It failed. Failure class (assigned by code): missing attribute or API (AttributeError).

Traceback (repository paths are relative to the repository root):
```
Traceback (most recent call last):
  File "train.py", line 299, in <module>
    train_method.train()
  File "algorithms/erm_match.py", line 149, in train
    self.val_acc.append( self.get_test_accuracy('val') )
  File "algorithms/algo.py", line 276, in get_test_accuracy
    opacus.autograd_grad_sample.enable_hooks()        
AttributeError: module 'opacus' has no attribute 'autograd_grad_sample'
```

Source around each repository frame of the traceback (line numbers on the left):
--- train.py:299 (lines 259-316) ---
```
  259                                  test_dataset, base_res_dir, 
  260                                  run, cuda
  261                                )           
  262      elif args.method_name == 'irm':
  263          from algorithms.irm import Irm    
  264          train_method= Irm(
  265                                  args, train_dataset, val_dataset,
  266                                  test_dataset, base_res_dir, 
  267                                  run, cuda
  268                                )
  269      elif args.method_name == 'dro':
  270          from algorithms.dro import DRO    
  271          train_method= DRO(
  272                                  args, train_dataset, val_dataset,
  273                                  test_dataset, base_res_dir, 
  274                                  run, cuda
  275                                )
  276      elif args.method_name == 'csd':
  277          from algorithms.csd import CSD   
  278          train_method= CSD(
  279                                  args, train_dataset, val_dataset,
  280                                  test_dataset, base_res_dir, 
  281                                  run, cuda
  282                                )
  283      elif args.method_name == 'mmd':
  284          from algorithms.mmd import MMD    
  285          train_method= MMD(
  286                                  args, train_dataset, val_dataset,
  287                                  test_dataset, base_res_dir, 
  288                                  run, cuda
  289                                )           
  290      elif args.method_name == 'dann':
  291          from algorithms.dann import DANN    
  292          train_method= DANN(
  293                                  args, train_dataset, val_dataset,
  294                                  test_dataset, base_res_dir, 
  295                                  run, cuda
  296                                )
  297          
  298      #Train the method: It will save the model's weights post training and evalute it on test accuracy
  299>     train_method.train()
  300              
  301      # Final Report Accuacy
  302      if args.method_name != 'matchdg_ctr':
  303          final_acc= np.max(train_method.final_acc)
  304          final_accuracy_target_val.append( final_acc )
  305          
  306          idx= np.argmax(train_method.val_acc)
  307          final_acc= train_method.final_acc[idx]
  308          final_accuracy_source_val.append( final_acc  )
  309          
  310          
  311  if args.method_name != 'matchdg_ctr':
  312      print('\n')
  313      print('Done for the Model..')
  314      print('Final Test Accuracy (Source Validation)', np.mean(final_accuracy_source_val), np.std(final_accuracy_source_val) )
  315      print('Final Test Accuracy (Target Validation)', np.mean(final_accuracy_target_val), np.std(final_accuracy_target_val) )
  316      print('\n')
```

--- algorithms/erm_match.py:149 (lines 109-174) ---
```
  109                          loss_e += ( self.args.penalty_ws*( epoch- self.args.penalty_s )/(self.args.epochs - self.args.penalty_s) )*wasserstein_loss
  110  
  111                          
  112                  loss_e.backward(retain_graph=False)
  113                  
  114                  if self.args.dp_noise and self.args.dp_attach_opt:
  115                      if batch_idx % 10 == 9:
  116                          self.opt.step()
  117                          self.opt.zero_grad()
  118                      else:
  119                          self.opt.virtual_step()                        
  120                  else:                    
  121                      self.opt.step()
  122                      self.opt.zero_grad()
  123                      
  124                  #Gradient Norm Computation
  125  #                 batch_grad_norm=0.0
  126  #                 for p in self.phi.parameters():
  127  #                     param_norm = p.grad.detach().data.norm(2)
  128  #                     batch_grad_norm += param_norm.item() ** 2
  129  #                 batch_grad_norm = batch_grad_norm ** 0.5
  130  #                 total_grad_norm.append( batch_grad_norm )
  131      
  132  #                 del out
  133                  del erm_loss
  134                  del wasserstein_loss 
  135                  del loss_e
  136                  torch.cuda.empty_cache()
  137                          
  138  
  139  #             print('Gradient Norm: ', total_grad_norm)
  140                      
  141              print('Train Loss Basic : ',  penalty_erm, penalty_ws )
  142              print('Train Acc Env : ', 100*train_acc/train_size )
  143              print('Done Training for epoch: ', epoch)
  144              
  145              #Train Dataset Accuracy
  146              self.train_acc.append( 100*train_acc/train_size )
  147              
  148              #Val Dataset Accuracy
  149>             self.val_acc.append( self.get_test_accuracy('val') )
  150              
  151              #Test Dataset Accuracy
  152              self.final_acc.append( self.get_test_accuracy('test') )
  153              
  154              #Save the model if current best epoch as per validation loss
  155              if self.val_acc[-1] > self.max_val_acc:
  156                  self.max_val_acc=self.val_acc[-1]
  157                  self.max_epoch= epoch
  158                  self.save_model()
  159                  
  160              print('Current Best Epoch: ', self.max_epoch, ' with Test Accuracy: ', self.final_acc[self.max_epoch])
  161              
  162              if epoch > 0 and self.args.model_name in ['domain_bed_mnist', 'lenet']:
  163                  if self.args.model_name == 'lenet':
  164                      lr_schedule_step= 25
  165                  elif self.args.model_name == 'domain_bed_mnist':
  166                      lr_schedule_step= 10
  167              
  168                  if epoch % lr_schedule_step==0 :
  169                      lr=self.args.lr/(2**(int(epoch/lr_schedule_step)))
  170                      print('Learning Rate Scheduling; New LR: ', lr)                
  171                      self.opt= optim.SGD([
  172                               {'params': filter(lambda p: p.requires_grad, self.phi.parameters()) }, 
  173                      ], lr= lr, weight_decay= self.args.weight_decay, momentum= 0.9,  nesterov=True )     
  174                  
```

--- algorithms/algo.py:276 (lines 236-316) ---
```
  236          
  237          return data_match_tensor, label_match_tensor, curr_batch_size
  238      
  239      def get_test_accuracy(self, case):
  240          import opacus
  241          
  242          if self.args.dp_noise:
  243              opacus.autograd_grad_sample.disable_hooks()
  244              #self.privacy_engine.module.disable_hooks()
  245          
  246          #Test Env Code
  247          test_acc= 0.0
  248          test_size=0
  249          if case == 'val':
  250              dataset= self.val_dataset
  251          elif case == 'test':
  252              dataset= self.test_dataset
  253  
  254          for batch_idx, (x_e, y_e ,d_e, idx_e, obj_e) in enumerate(dataset):
  255              with torch.no_grad():
  256                  
  257                  self.opt.zero_grad()
  258  #                 print(x_e.shape)
  259  #                 print(torch.cuda.memory_allocated())                
  260                  x_e= x_e.to(self.cuda)
  261                  y_e= torch.argmax(y_e, dim=1).to(self.cuda)
  262  
  263                  #Forward Pass
  264                  out= self.phi(x_e)                
  265                  
  266                  test_acc+= torch.sum( torch.argmax(out, dim=1) == y_e ).item()
  267                  test_size+= y_e.shape[0]
  268                  
  269                  # To avoid CUDA memory issues
  270                  if self.args.dp_noise:
  271                      self.opt.zero_grad()
  272  
  273          print(' Accuracy: ', case, 100*test_acc/test_size )         
  274                  
  275          #self.privacy_engine.module.enable_hooks()
  276>         opacus.autograd_grad_sample.enable_hooks()        
  277          return 100*test_acc/test_size
  278      
  279      def get_dp_noise(self):
  280          
  281          print('Privacy Engine')
  282          print('Total Domains: ', self.total_domains, ' Domain Size ', self.domain_size, ' Batch Size ', self.args.batch_size)
  283          
  284          from opacus.dp_model_inspector import DPModelInspector
  285          from opacus.utils import module_modification
  286          
  287          inspector = DPModelInspector()        
  288  #         self.phi = module_modification.convert_batchnorm_modules(self.phi) 
  289          inspector.validate(self.phi)
  290          
  291          MAX_GRAD_NORM = 5.0
  292          DELTA = 1.0/(self.total_domains*self.domain_size)
  293          BATCH_SIZE = self.args.batch_size * self.total_domains
  294          SAMPLE_RATE = BATCH_SIZE /(self.total_domains*self.domain_size)
  295          DEFAULT_ALPHAS = [1 + x / 10.0 for x in range(1, 100)] + list(range(12, 64))
  296                  
  297          NOISE_MULTIPLIER = get_noise_multiplier(self.args.dp_epsilon, DELTA, SAMPLE_RATE, self.args.epochs, DEFAULT_ALPHAS)
  298          
  299          print("Target Epsilon: ", self.args.dp_epsilon)
  300          print(f"Using sigma={NOISE_MULTIPLIER} and C={MAX_GRAD_NORM}")
  301          
  302                  
  303          from opacus import PrivacyEngine        
  304          privacy_engine = PrivacyEngine(
  305              self.phi,
  306              batch_size= BATCH_SIZE,
  307              sample_size= self.total_domains*self.domain_size,
  308              noise_multiplier=NOISE_MULTIPLIER,
  309              max_grad_norm=MAX_GRAD_NORM,
  310          )
  311          
  312          if self.args.dp_attach_opt:
  313              print('Standard DP Training with finite epsilon')
  314              privacy_engine.attach(self.opt)
  315          else:
  316              print('DP Training with infinite epsilon')
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
