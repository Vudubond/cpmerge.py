#!/usr/bin/python
"""
Author: Tom Ludwig
Date: 02/06/19
About:
    - T2S-II project
Purpose:
    - provide a means of quickly merging cpanel accounts
Why:
    - address the need to merge cpanel accounts easily
    -- see Internal Migrations queue for more details
Actions:
    - merges one cpanel into another cpanel account
Requires:
    - 
"""
import sys
import argparse
import subprocess
import os
import shutil
import time
import pwd
import json
import logging
import yaml
from collections import defaultdict
logger = logging.getLogger(__name__)
def fix_perms(cp_obj):
    proc = subprocess.Popen(['/usr/bin/fixperms', cp_obj.tocp], \
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = proc.communicate()
def rename_main(cp_obj):
    """ Rename primary domain to prevent domain name conflict """
    for domain in cp_obj.domains["main"]:
        logger.info("Changing primary domain of fromcp cpanel...")
        call_user = 'user=' + cp_obj.fromcp
        call_domain = 'domain=' + domain + '.cpmerge'
        proc = subprocess.Popen(['whmapi1', 'modifyacct', call_user, call_domain], \
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, err = proc.communicate()
        if 'result: 1' not in output:
            logger.error("Renaming primary domain failed.\n {} \n {}".format(output, err))
            cp_obj.has_errors = True
def add_main(cp_obj):
    """ Add the fromcp's primary domain to tocp cpanel as an addon """
    for domain in cp_obj.domains["main"]:
        logger.info("Adding main domain {}".format(domain))
        call_user = '--user=' + cp_obj.tocp
        call_domain = 'newdomain=' + domain
        call_subdomain = 'subdomain=' + domain.split('.', 1)[0]
        call_docroot = 'dir=' + cp_obj.merge_dir + domain
        proc = subprocess.Popen(['cpapi2', call_user, 'AddonDomain', 'addaddondomain', \
                                call_docroot, call_domain, call_subdomain], \
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, err = proc.communicate()
        if 'result: 1' not in output:
            logger.error("Adding main domain failed.\n {} \n {}".format(output, err))
            cp_obj.has_errors = True
def move_homedir(cp_obj):
    """ Move fromcps home directory """
    if is_realpath(cp_obj, '/home/' + cp_obj.fromcp):
        try:
            shutil.move('/home/' + cp_obj.fromcp, '/home/' + cp_obj.tocp)
            os.chown('/home/' + cp_obj.tocp + '/' + cp_obj.fromcp, cp_obj.uid, cp_obj.gid)
        except (OSError, IOError) as err:
            logger.error("Error moving home dir: \n{}".format(os.strerror(err.errno)))
def move_maildirs(cp_obj):
    """ Move the mail directories """
    logger.info("Moving mail directories...")
    try:
        for addon in cp_obj.domains["addondomains"]:
            if is_realpath(cp_obj, '/home/' + cp_obj.fromcp + '/mail/' + addon):
                shutil.move('/home/' + cp_obj.fromcp + '/mail/' + addon, \
                            '/home/' + cp_obj.tocp + '/mail/')
            if is_realpath(cp_obj, '/home/' + cp_obj.fromcp + '/etc/' + addon):
                shutil.move('/home/' + cp_obj.fromcp + '/etc/' + addon, \
                            '/home/' + cp_obj.tocp + '/etc/')
        for subdomain in cp_obj.domains["subdomains"]:
            if is_realpath(cp_obj, '/home/' + cp_obj.fromcp + '/mail/' + subdomain):
                shutil.move('/home/' + cp_obj.fromcp + '/mail/' + subdomain, \
                            '/home/' + cp_obj.tocp + '/mail/')
            if is_realpath(cp_obj, '/home/' + cp_obj.fromcp + '/etc/' + subdomain):
                shutil.move('/home/' + cp_obj.fromcp + '/etc/' + subdomain, \
                            '/home/' + cp_obj.tocp + '/etc/')
        for domain in cp_obj.domains["main"]:
            if is_realpath(cp_obj, '/home/' + cp_obj.fromcp + '/mail/' + domain):
                shutil.move('/home/' + cp_obj.fromcp + '/mail/' + domain, \
                            '/home/' + cp_obj.tocp + '/mail/')
            if is_realpath(cp_obj, '/home/' + cp_obj.fromcp + '/etc/' + domain):
                shutil.move('/home/' + cp_obj.fromcp + '/etc/' + domain, \
                            '/home/' + cp_obj.tocp + '/etc/')
    except (OSError, IOError) as err:
        logger.error("Error moving mail directories: \n{}".format(os.strerror(err.errno)))
        cp_obj.has_errors = True
def move_docroots(cp_obj):
    """ Move all domains docroots """
    for addon in cp_obj.domains["addondomains"]:
        logger.info("Moving addon docroot for {}".format(addon))
        old_docroot = cp_obj.domains["addondomains"][addon]["docroot"]
        try:
            if is_realpath(cp_obj, old_docroot):
                shutil.move(old_docroot, cp_obj.merge_dir)
        except (OSError, IOError) as err:
            logger.error("Error moving document root: \n{}".format(os.strerror(err.errno)))
            cp_obj.has_errors = True
    for subdomain in cp_obj.domains["subdomains"]:
        logger.info("Moving subdomain docroot for {}".format(subdomain))
        old_docroot = cp_obj.domains["subdomains"][subdomain]
        try:
            if is_realpath(cp_obj, old_docroot):
                shutil.move(old_docroot, cp_obj.merge_dir)
        except (OSError, IOError) as err:
            logger.error("Error moving document root: \n{}".format(os.strerror(err.errno)))
            cp_obj.has_errors = True
    # move data for fromcp primary domain last otherwise we move all sub/addon dirs too
    for domain in cp_obj.domains["main"]:
        main_docroot = cp_obj.domains["main"][domain]
        logger.info("Moving main docroot {}".format(main_docroot))
        try:
            if is_realpath(cp_obj, main_docroot):
                os.rename(main_docroot, cp_obj.merge_dir + domain)
        except (OSError, IOError) as err:
            logger.error("Error moving document root: \n{}".format(os.strerror(err.errno)))
            cp_obj.has_errors = True
def del_addons(cp_obj):
    """ Loop through and remove addons """
    for addon in cp_obj.domains["addondomains"]:
        call_user = '--user=' + cp_obj.fromcp
        call_domain = 'domain=' + addon
        call_subdomain = 'subdomain=' + cp_obj.domains["addondomains"][addon]["subdomain"]
        logger.info("Deleting addon {}".format(addon))
        proc = subprocess.Popen(['cpapi2', call_user, 'AddonDomain', 'deladdondomain', \
                                call_domain, call_subdomain], stdout=subprocess.PIPE, \
                                stderr=subprocess.PIPE)
        output, err = proc.communicate()
        if 'result: 1' not in output:
            logger.error("Error deleting addon: \n{}".format(output))
            cp_obj.has_errors = True
def add_addons(cp_obj):
    """ Add fromcp's addons in loop to tocp cpanel """
    for addon in cp_obj.domains["addondomains"]:
        call_user = '--user=' + cp_obj.tocp
        call_domain = 'newdomain=' + addon
        # remove (tld) to create subdomain
        call_subdomain = 'subdomain=' + addon.split('.', 1)[0]
        new_docroot = cp_obj.merge_dir + \
                        os.path.basename(os.path.normpath(cp_obj.domains["addondomains"][addon]["docroot"]))
        call_docroot = 'dir=' + new_docroot
        # cpanel requires deleting the subdomain too
        logger.info("Adding addon {}".format(addon))
        proc = subprocess.Popen(['cpapi2', call_user, 'AddonDomain', 'addaddondomain', \
                                call_docroot, call_domain, call_subdomain], \
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, err = proc.communicate()
        if 'result: 1' not in output:
            logger.error("Error adding addon domain: \n{}".format(output))
            cp_obj.has_errors = True
def add_subdomains(cp_obj):
    """ Add fromcp's subdomains in loop to tocp cpanel """
    for subdomain in cp_obj.domains["subdomains"]:
        call_user = '--user=' + cp_obj.tocp
        call_domain = 'domain=' + subdomain.split('.', 1)[0]
        call_rootdomain = 'rootdomain=' + subdomain.split('.', 1)[1]
        new_docroot = cp_obj.merge_dir + \
                        os.path.basename(os.path.normpath(cp_obj.domains["subdomains"][subdomain]))
        call_docroot = 'dir=' + new_docroot
        logger.info("Adding subdomain {}".format(subdomain))
        proc = subprocess.Popen(['cpapi2', call_user, 'SubDomain', 'addsubdomain', call_domain, \
                                call_rootdomain, call_docroot, 'disallowdot=1'], \
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, err = proc.communicate()
        if 'result: 1' not in output:
            logger.error("Error adding subdomain: \n{}".format(output))
            cp_obj.has_errors = True
def reassign_dbs(cp_obj):
    """ Assign fromcp's mysql dbs, users, and grants to the tocp cpanel """
    logger.info("Assigning databases and users to tocp cpanel...")
    call_user = '--user=' + cp_obj.fromcp
    mysql_fail = False
    pgsql_fail = False
    proc = subprocess.Popen(['cpapi2', call_user, 'MysqlFE', 'listdbs', '--output=json'], \
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    json_output, err = proc.communicate()
    try:
        json_mysql = json.loads(json_output)
    except ValueError as err:
        logger.error("Decoding mysql json failed: \n{}".format(err))
        mysql_fail = True
    proc = subprocess.Popen(['cpapi2', call_user, 'Postgres', 'listdbs', '--output=json'], \
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    json_output, err = proc.communicate()
    try:
        json_pgsql = json.loads(json_output)
    except ValueError as err:
        logger.error("Decoding pgsql json failed: \n{}".format(err))
        pgsql_fail = True
    # if both are unreadable don't continue
    if mysql_fail and pgsql_fail:
        return
    # address edge cases missing grant files
    if not os.path.isfile('/var/cpanel/userdata/grants_' + cp_obj.tocp + '.yaml'):
        proc = subprocess.Popen(['/usr/local/cpanel/bin/dbstoregrants', cp_obj.tocp], \
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, err = proc.communicate()
    if not os.path.isfile('/var/cpanel/userdata/grants_' + cp_obj.fromcp + '.yaml'):
        proc = subprocess.Popen(['/usr/local/cpanel/bin/dbstoregrants', cp_obj.tocp], \
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, err = proc.communicate()
    try:
        if not mysql_fail:
            has_mysql_dbs = json_mysql["cpanelresult"]["data"]
        if not pgsql_fail:
            has_pgsql_dbs = json_pgsql["cpanelresult"]["data"]
    except IndexError as err:
        logger.error("Database reassignment failed!\n{}".format(str(err)))
        cp_obj.has_errors = True
    else:
        # Check for mysql dbs
        if has_mysql_dbs or has_pgsql_dbs:
            try:
                with open('/var/cpanel/databases/' + cp_obj.fromcp + '.json', 'r') as infile:
                    fromcp_json = json.load(infile)
                    infile.close
                    try:
                        if has_mysql_dbs:
                            fromcp_mysql_dbs = fromcp_json['MYSQL']['dbs']
                            fromcp_mysql_dbusers = fromcp_json['MYSQL']['dbusers']
                        if has_pgsql_dbs:
                            fromcp_pgsql_dbs = fromcp_json['PGSQL']['dbs']
                            fromcp_pgsql_dbusers = fromcp_json['PGSQL']['dbusers']
                    except IndexError as err:
                        logger.error("Database reassignment failed!\n{}".format(str(err)))
                        cp_obj.has_errors = True
                    else:
                        with open('/var/cpanel/databases/' + cp_obj.tocp + '.json', 'r') as infile:
                            tocp_json = json.load(infile)
                            infile.close
                            # check if pgsql is empty because cpanel
                            if 'dbusers' not in tocp_json['PGSQL']:
                                logger.info("Empty PGSQL json updating...")
                                pgsql_dict = {'dbs':{}, 'dbusers':{}, 'noprefix':{}, 'owner':"", 'server':""}
                                tocp_json['PGSQL'].update(pgsql_dict)
                            try:
                                if has_mysql_dbs:
                                    tocp_json['MYSQL']['dbusers'].update(fromcp_mysql_dbusers)
                                    tocp_json['MYSQL']['dbs'].update(fromcp_mysql_dbs)
                                if has_pgsql_dbs:
                                    tocp_json['PGSQL']['dbusers'].update(fromcp_pgsql_dbusers)
                                    tocp_json['PGSQL']['dbs'].update(fromcp_pgsql_dbs)
                            except IndexError as err:
                                logger.error("Database reassignment failed!\n{}".format(str(err)))
                                cp_obj.has_errors = True
                            else:
                                with open('/var/cpanel/databases/' + cp_obj.tocp + '.json', 'w') as outfile:
                                    json.dump(tocp_json, outfile)
                                    outfile.close()
                                # made it this far, update database grant files
                                with open('/var/cpanel/databases/grants_' + cp_obj.fromcp + '.yaml', 'r') as stream:
                                    try:
                                        fromcp_yaml = yaml.safe_load(stream)
                                        if has_mysql_dbs:
                                            fromcp_mysql_grants = fromcp_yaml['MYSQL'][cp_obj.fromcp]
                                        if has_pgsql_dbs:
                                            fromcp_pgsql_grants = fromcp_yaml['PGSQL'][cp_obj.fromcp]
                                    except yaml.YAMLError as err:
                                        logger.error(str(err))
                                    else:
                                        with open('/var/cpanel/databases/grants_' + cp_obj.tocp + '.yaml', 'r') as stream:
                                            try:
                                                tocp_yaml = yaml.safe_load(stream)
                                                if has_mysql_dbs:
                                                    tocp_yaml['MYSQL'][cp_obj.tocp].update(fromcp_mysql_grants)
                                                if has_pgsql_dbs:
                                                    tocp_yaml['PGSQL'][cp_obj.tocp].update(fromcp_pgsql_grants)
                                            except yaml.YAMLError as err:
                                                logger.error(str(err))
                                            else:
                                                with open('/var/cpanel/databases/grants_' + cp_obj.tocp + '.yaml', 'w') as yamlfile:
                                                    yaml.safe_dump(tocp_yaml, yamlfile, default_flow_style=False)
                                                # Move db files out of the way so removeacct won't remove db users
                                                if os.path.isfile('/var/cpanel/databases/grants_' + cp_obj.fromcp + '.yaml'):
                                                    shutil.move('/var/cpanel/databases/grants_' + cp_obj.fromcp + '.yaml', \
                                                                '/var/cpanel/databases/grants_' + cp_obj.fromcp + '-' + \
                                                                time.strftime("%Y%m%d-%H%M%S"))
                                                if os.path.isfile('/var/cpanel/databases/' + cp_obj.fromcp + '.json'):
                                                    shutil.move('/var/cpanel/databases/' + cp_obj.fromcp + '.json', \
                                                                '/var/cpanel/databases/' + cp_obj.fromcp + '.json' + \
                                                                '-' + time.strftime("%Y%m%d-%H%M%S"))
            except IOError as err:
                logger.error("Database json/yaml file open error:\n{}".format(os.strerror(err.errno)))
                cp_obj.has_errors = True
        else:
            logger.info("No databases found.")
def is_confirmed(cp_obj):
    """ Confirm primary cpanel and cpanel to be merged """
    while "invalid input":
        reply = str(raw_input('Requesting to merge ' + cp_obj.fromcp + ' => ' + cp_obj.tocp + \
                    ':\nIs ' + cp_obj.tocp + ' the primary cpanel that will remain after ' + \
                    'the merge? (y/n): ')).lower().strip()
        if reply[:1] == 'y':
            return True
        if reply[:1] == 'n':
            return False
def is_realpath(cp_obj, path):
    home_path = '/home/' + cp_obj.fromcp
    lepath = os.path.realpath(path)
    return lepath.startswith(home_path)
def backupdns(cp_obj):
    """ Make a backup of DNS since removing addons removes DNS """
    try:
        for addon in cp_obj.domains["addondomains"]:
            dns_path = '/var/named/' + addon + '.db'
            if os.path.isfile(dns_path):
                shutil.copy2(dns_path, dns_path + '_' + time.strftime("%Y%m%d-%H%M%S"))
        for domain in cp_obj.domains["main"]:
            dns_path = '/var/named/' + domain + '.db'
            if os.path.isfile(dns_path):
                shutil.copy2(dns_path, dns_path + '_' + time.strftime("%Y%m%d-%H%M%S"))
    except OSError as err:
        logger.error("Error backing up DNS: \n{}".format(os.strerror(err.errno)))
def setup_logging(cp_obj, name):
    """ Create log """
    logdir = '/home/' + cp_obj.tocp + '/.imh'
    logfile = '/home/' + cp_obj.tocp + '/.imh/cpmerge.log'
    if not os.path.isdir(logdir):
        os.makedirs(logdir)
        os.chown(logdir, cp_obj.uid, cp_obj.gid)
    logger.setLevel(logging.DEBUG)
    try:
        # Create handlers
        c_handler = logging.StreamHandler()
        f_handler = logging.FileHandler(logfile)
        c_handler.setLevel(logging.INFO)
        f_handler.setLevel(logging.DEBUG)
        # Create formatters and add it to handlers
        c_format = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
        f_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        c_handler.setFormatter(c_format)
        f_handler.setFormatter(f_format)
        # Add handlers to the logger
        logger.addHandler(c_handler)
        logger.addHandler(f_handler)
    except Exception as e:
        logger.warning("Failed to open logfile: %s", str(e))
class Cpmerge:
    """
    Store users and paths, set primary cpanel unlimited quotas, and validate users
    """
    def __init__(self, tocp, fromcp):
        self.are_users_valid(tocp, fromcp)
        self.tocp = tocp # cpanel acquiring other cpanel
        self.fromcp = fromcp # cpanel being acquired
        self.domains = self.set_domains()
        self.uid = self.get_uid()
        self.gid = self.get_gid()
        self.nobody_gid = self.get_nobody_gid()
        self.set_unlimited_quotas(tocp)
        self.merge_dir = self.get_merge_dir()
        self.can_access_api()
        self.has_errors = False
    def are_users_valid(self, tocp, fromcp):
        """ Check if user exists """
        tocp = 'user=' + tocp
        fromcp = 'user=' + fromcp
        proc = subprocess.Popen(['whmapi1', 'validate_system_user', tocp], \
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        tocp_data, err = proc.communicate()
        proc = subprocess.Popen(['whmapi1', 'validate_system_user', fromcp], \
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        fromcp_data, err = proc.communicate()
        bool_exists = 'exists: 1' in tocp_data and 'exists: 1' in fromcp_data
        if not bool_exists:
            sys.exit("Unable to continue: user not found.")
    def set_unlimited_quotas(self, tocp):
        """ Set unlimited addons/subdomains/mysql """
        call_user = 'user=' + tocp
        proc = subprocess.Popen(['whmapi1', 'modifyacct', call_user, 'MAXSUB=unlimited', \
                    'MAXSQL=unlimited', 'MAXPARK=unlimited', 'MAXADDON=unlimited', \
                    'MAXPOP=unlimited', 'MAXFTP=unlimited'], stdout=subprocess.PIPE, \
                    stderr=subprocess.PIPE)
        output, err = proc.communicate()
        if 'result: 1' not in output:
            sys.exit("Unable to continue: unable to increase quotas.")
    def get_uid(self):
        """ Get the UID """
        try:
            uid = pwd.getpwnam(self.tocp).pw_uid
        except OSError:
            sys.exit("Error finding UID")
        return uid
    def get_gid(self):
        """ Get the GID """
        try:
            gid = pwd.getpwnam(self.tocp).pw_gid
        except TypeError:
            sys.exit("Error finding group id of user")
        return gid
    def get_nobody_gid(self):
        """ Get nobody GID """
        try:
            gid = pwd.getpwnam('nobody').pw_gid
        except TypeError:
            sys.exit("Error finding group id of user")
        return gid
    def set_domains(self):
        """ Get all fromcp's domains/subdomains/addon data """
        call_user = '--user=' + self.fromcp
        domain_dict = defaultdict(dict)
        proc = subprocess.Popen(['uapi', call_user, 'DomainInfo', 'domains_data', \
                '--output=json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        json_domains, err = proc.communicate()
        try:
            json_domains = (json.loads(json_domains))
            for dom in json_domains["result"]["data"]["sub_domains"]:
                subdomain = dom["domain"]
                docroot = dom["documentroot"]
                domain_dict["subdomains"][subdomain] = docroot
            for dom in json_domains["result"]["data"]["addon_domains"]:
                addon = dom["domain"]
                docroot = dom["documentroot"]
                subdomain = dom["servername"]
                domain_dict["addondomains"][addon] = {"docroot": docroot, "subdomain": subdomain}
            domain = json_domains["result"]["data"]["main_domain"]["servername"]
            docroot = json_domains["result"]["data"]["main_domain"]["documentroot"]
            domain_dict["main"][domain] = docroot
        except IndexError as err:
            print err
            sys.exit("Unable to continue: error parsing users domains.")
        return domain_dict
    def get_merge_dir(self):
        """ prevent collisions with matching dir names: timestampe append """
        merge_dir = '/home/' + self.tocp + '/public_html/' + self.fromcp \
                    + '_domains_' + time.strftime("%Y%m%d-%H%M%S") + '/'
        try:
            os.mkdir(merge_dir)
            os.chown(merge_dir, self.uid, self.gid)
        except OSError as err:
            print err
            sys.exit("Directory already exists: exiting")
        return merge_dir
    def can_access_api(self):
        """ Test WHMAPI access """
        proc = subprocess.Popen(['whmapi1', 'version', '--output=yaml'], \
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, err = proc.communicate()
        if 'result: 1' not in output:
            logging.info("Cannot access WHMAPI. Exiting.")
            sys.exit()
def main():
    """
    Merge two cpanel accounts
    Required:
        - two cpanel accounts (tocp and fromcp)
    Actions:
        - creates a cp object to store data
        - moves all data to the tocp cpanel
        - backs up DNS
    Checks: valid cpanel users
    """
    parser = argparse.ArgumentParser(description='Merge two cpanel accounts')
    parser.add_argument('--tocp', \
                        required=True, \
                        help='primary cpanel that will remain after merge')
    parser.add_argument('--fromcp', \
                        required=True, \
                        help='cpanel that will not remain')
    args = parser.parse_args()
    cp_obj = Cpmerge(args.tocp, args.fromcp)
    setup_logging(cp_obj, __name__)
    logger.debug("Merging {} into {}".format(cp_obj.fromcp, cp_obj.tocp))
    if is_confirmed(cp_obj):
        """
        - Move docroots/conf files before renaming main cpanel
        - Must add main domain before we can add subdomains
        """
        backupdns(cp_obj)
        move_maildirs(cp_obj)
        move_docroots(cp_obj)
        del_addons(cp_obj)
        add_addons(cp_obj)
        rename_main(cp_obj)
        add_main(cp_obj)
        add_subdomains(cp_obj)
        reassign_dbs(cp_obj)
        fix_perms(cp_obj)
        if not cp_obj.has_errors:
            logger.info("Moving homedir...")
            move_homedir(cp_obj)
        if cp_obj.has_errors:
            logger.info("Completed with errors: please check the .imh/cpmerge.log for errors")
        else:
            logger.info("Completed successfully!")
    else:
        print "Exiting."
if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit()
