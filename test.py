import yaml
file_path = 'test.repos'
with open(file_path) as f:
    res = yaml.safe_load(f)
    print(res)
    repos =[v['url'].split('/')[-1].split('.')[0] for k,v in res['repositories'].items()]
    print(repos)