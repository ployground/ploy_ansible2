from ansible import utils
from ansible.inventory import Group
from ansible.inventory import Host as BaseHost
from ansible.inventory import Inventory as BaseInventory
import inspect
import logging


log = logging.getLogger('ploy_ansible.inventory')


class PloyInventoryDict(dict):
    def __getitem__(self, name):
        if name.startswith('awsome_'):
            caller_frame = inspect.currentframe().f_back
            info = inspect.getframeinfo(caller_frame)
            new_name = "ploy_%s" % name[7:]
            log.warning("Use of deprecated variable name '%s', use '%s' instead.\n%s:%s\n%s" % (
                name, new_name, info.filename, info.lineno, ''.join(info.code_context)))
        return dict.__getitem__(self, name)


class Host(BaseHost):
    def __init__(self, ctrl, name):
        BaseHost.__init__(self, name)
        self.ctrl = ctrl

    def get_variables(self):
        instance = self.ctrl.instances[self.name]
        results = dict(
            ansible_connection='execnet_connection',
            ansible_ssh_user=instance.config.get('user', 'root'),
            _ploy_instance=instance,
            _ploy_instances=self.ctrl.instances)
        for k, v in instance.config.items():
            if k == 'password' and instance.config['password-fallback']:
                results['ansible_ssh_pass'] = v
            elif k.startswith('ansible_'):
                results[k] = v
            elif k.startswith('ansible-'):
                results[k[len('ansible-'):].replace('-', '_')] = v
            else:
                results['ploy_%s' % k.replace('-', '_')] = v
                results['awsome_%s' % k.replace('-', '_')] = v
        groups = self.get_groups()
        for group in sorted(groups, key=lambda g: g.depth):
            results = utils.combine_vars(results, group.get_variables())
        results = utils.combine_vars(results, self.vars)
        results['inventory_hostname'] = self.name
        results['inventory_hostname_short'] = self.name.split('.')[0]
        results['group_names'] = sorted([g.name for g in groups if g.name != 'all'])
        return results


class Inventory(BaseInventory):
    def __init__(self, ctrl, vault_password=None):
        from ploy_ansible import get_playbooks_directory
        kwargs = dict(host_list=[])
        if vault_password is not None:
            kwargs['vault_password'] = vault_password
        BaseInventory.__init__(self, **kwargs)
        self.ctrl = ctrl
        self.set_playbook_basedir(get_playbooks_directory(ctrl.config))
        groups = {}
        groups['all'] = self.get_group('all')
        seen = set()
        for instance in self.ctrl.instances.values():
            if instance.uid in seen:
                continue
            seen.add(instance.uid)
            h = Host(ctrl, instance.uid)
            add_to = ['all', '%ss' % instance.sectiongroupname]
            if hasattr(instance, 'master'):
                master = instance.master
                if instance == getattr(master, 'instance', None):
                    add_to.append('masters')
                else:
                    add_to.append('%s-instances' % master.id)
            for group in add_to:
                g = groups.get(group)
                if g is None:
                    g = self.get_group(group)
                    if g is None:
                        g = Group(group)
                        self.add_group(g)
                    groups[group] = g
                g.add_host(h)
        self._vars_plugins = [x for x in utils.plugins.vars_loader.all(self)]
        self._hosts_cache.clear()
        self._pattern_cache.clear()
        if hasattr(self, 'get_host_variables'):
            for host in self.get_hosts():
                host.vars = utils.combine_vars(
                    host.vars,
                    self.get_host_variables(
                        host.name, vault_password=self._vault_password))

    def get_variables(self, hostname, **kwargs):
        return PloyInventoryDict(BaseInventory.get_variables(self, hostname, **kwargs))
