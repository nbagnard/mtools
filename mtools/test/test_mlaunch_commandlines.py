import os
import json
import sys
import unittest
import inspect
import shutil
import subprocess

from mtools.mlaunch.mlaunch import MLaunchTool, shutdown_host
from nose.tools import *
from nose.plugins.attrib import attr
from nose.plugins.skip import Skip, SkipTest
from pprint import pprint
from distutils.version import LooseVersion


class TestMLaunch(unittest.TestCase):

    # Setup & teardown functions

    def setUp(self):
        self.base_dir = 'data_test_mlaunch'
        self.tool = MLaunchTool(test=True)
        self.tool.args = {'verbose': False}
        self.mongod_version = self.tool.getMongoDVersion()

    def tearDown(self):
        self.tool = None
        if os.path.exists(self.base_dir):
            shutil.rmtree(self.base_dir)


    # Helper functions

    def run_tool(self, arg_str):
        ''' wrapper to call self.tool.run() with or without auth '''
        # name data directory according to test method name
        caller = inspect.stack()[1][3]
        self.data_dir = os.path.join(self.base_dir, caller)

        # add data directory to arguments for all commands
        arg_str += ' --dir %s' % self.data_dir

        with self.assertRaises(SystemExit):
            self.tool.run(arg_str)

    def read_config(self):
        ''' read the generated mlaunch startup file, get the command lines '''
        fp = open(self.data_dir + '/.mlaunch_startup', 'r')
        cfg = json.load(fp)
        cmd = [cfg['startup_info'][x] for x in cfg['startup_info'].keys()]
        return cfg, cmd

    def cmdlist_filter(self, cmdlist):
        ''' filter command lines to contain only [mongod|mongos] --parameter '''
        res = map(lambda cmd: set([param for param in cmd.split() if param.startswith('mongo') or param.startswith('--')]),
            [cmd for cmd in cmdlist if cmd.startswith('mongod') and '--configsvr' in cmd]
          + [cmd for cmd in cmdlist if cmd.startswith('mongod') and '--shardsvr' in cmd]
          + [cmd for cmd in cmdlist if cmd.startswith('mongod') and '--configsvr' not in cmd and '--shardsvr' not in cmd]
          + [cmd for cmd in cmdlist if cmd.startswith('mongos')]
        )
        return res

    def cmdlist_print(self):
        ''' print the generated command lines to console '''
        cfg, cmdlist = self.read_config()
        print '\n'
        print cmdlist
        print '\n'
        cmdset = self.cmdlist_filter(cmdlist)
        for cmd in cmdset:
            print cmd

    def cmdlist_assert(self, cmdlisttest):
        ''' assert helper for command lines '''
        cfg, cmdlist = self.read_config()
        cmdset = [set(x) for x in self.cmdlist_filter(cmdlist)]
        self.assertEqual(len(cmdlist), len(cmdlisttest), 'number of command lines is {0}, should be {1}'.format(len(cmdlisttest), len(cmdlist)))
        for cmd in zip(cmdset, cmdlisttest):
            self.assertSetEqual(cmd[0], cmd[1])

    def check_csrs(self):
        ''' check if CSRS is supported, skip test if unsupported '''
        if LooseVersion(self.mongod_version) < LooseVersion('3.1.0'):
            self.skipTest('CSRS not supported by MongoDB < 3.1.0')

    def check_sccc(self):
        ''' check if SCCC is supported, skip test if unsupported '''
        if LooseVersion(self.mongod_version) >= LooseVersion('3.3.0'):
            self.skipTest('SCCC not supported by MongoDB >= 3.3.0')

    def check_3_4(self):
        ''' check for MongoDB 3.4, skip test otherwise '''
        if LooseVersion(self.mongod_version) < LooseVersion('3.4.0'):
            self.skipTest('MongoDB version is < 3.4.0')


    # Tests

    def test_single(self):
        ''' mlaunch should start 1 node '''
        self.run_tool('init --single')
        cmdlist = [
            {'mongod', '--dbpath', '--logpath', '--port', '--logappend', '--fork'}
        ]
        self.cmdlist_assert(cmdlist)

    def test_replicaset(self):
        ''' mlaunch should start 3 nodes replicaset '''
        self.run_tool('init --replicaset')
        cmdlist = (
            [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork'} ] * 3
        )
        self.cmdlist_assert(cmdlist)

    def test_replicaset(self):
        ''' mlaunch should start 7 nodes replicaset '''
        self.run_tool('init --replicaset --nodes 7')
        cmdlist = (
            [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork'} ] * 7
        )
        self.cmdlist_assert(cmdlist)

    def test_replicaset(self):
        ''' mlaunch should start 6 nodes + 1 arbiter replicaset '''
        self.run_tool('init --replicaset --nodes 6 --arbiter')
        cmdlist = (
            [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork'} ] * 7
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_single(self):
        ''' mlaunch should start 1 config, 2 single shards 1 mongos '''
        self.run_tool('init --sharded 2 --single')
        if LooseVersion(self.mongod_version) >= LooseVersion('3.3.0'):
            cmdlist = (
                [ {'mongod', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--replSet', '--configsvr'} ]
              + [ {'mongod', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--shardsvr'} ] * 2
              + [ {'mongos', '--logpath', '--port', '--configdb', '--logappend', '--fork'} ] )
        else:
            cmdlist = (
                [ {'mongod', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--configsvr'} ]
              + [ {'mongod', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--shardsvr'} ] * 2
              + [ {'mongos', '--logpath', '--port', '--configdb', '--logappend', '--fork'} ] )
        self.cmdlist_assert(cmdlist)

    def test_sharded_replicaset_sccc_1(self):
        ''' mlaunch should start 1 config, 2 shards (3 nodes each), 1 mongos (SCCC) '''
        self.check_sccc()
        self.run_tool('init --sharded 2 --replicaset')
        cmdlist = (
            [ {'mongod', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--configsvr'} ]
          + [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--shardsvr'} ] * 6
          + [ {'mongos', '--logpath', '--port', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_replicaset_sccc_2(self):
        ''' mlaunch should start 1 config, 2 shards (3 nodes each), 1 mongos (SCCC) '''
        self.check_sccc()
        self.run_tool('init --sharded 2 --replicaset --config 2')
        cmdlist = (
            [ {'mongod', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--configsvr'} ]
          + [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--shardsvr'} ] * 6
          + [ {'mongos', '--logpath', '--port', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_replicaset_sccc_3(self):
        ''' mlaunch should start 3 config, 2 shards (3 nodes each), 1 mongos (SCCC) '''
        self.check_sccc()
        self.run_tool('init --sharded 2 --replicaset --config 3')
        cmdlist = (
            [ {'mongod', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--configsvr'} ] * 3
          + [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--shardsvr'} ] * 6
          + [ {'mongos', '--logpath', '--port', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_replicaset_sccc_4(self):
        ''' mlaunch should start 3 config, 2 shards (3 nodes each), 1 mongos (SCCC) '''
        self.check_sccc()
        self.run_tool('init --sharded 2 --replicaset --config 4')
        cmdlist = (
            [ {'mongod', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--configsvr'} ] * 3
          + [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--shardsvr'} ] * 6
          + [ {'mongos', '--logpath', '--port', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_replicaset_csrs_1(self):
        ''' mlaunch should start 1 replicaset config, 2 shards (3 nodes each), 1 mongos (CSRS) '''
        self.check_csrs()
        self.run_tool('init --sharded 2 --replicaset --config 1 --csrs')
        cmdlist = (
            [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--configsvr'} ]
          + [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--shardsvr'} ] * 6
          + [ {'mongos', '--logpath', '--port', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_replicaset_csrs_2(self):
        ''' mlaunch should start 2 replicaset config, 2 shards (3 nodes each), 1 mongos (CSRS) '''
        self.check_csrs()
        self.run_tool('init --sharded 2 --replicaset --config 2 --csrs')
        cmdlist = (
            [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--configsvr'} ] * 2
          + [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--shardsvr'} ] * 6
          + [ {'mongos', '--logpath', '--port', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_replicaset_csrs_3(self):
        ''' mlaunch should start 3 replicaset config, 2 shards (3 nodes each), 1 mongos (CSRS) '''
        self.check_csrs()
        self.run_tool('init --sharded 2 --replicaset --config 3 --csrs')
        cmdlist = (
            [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--configsvr'} ] * 3
          + [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--shardsvr'} ] * 6
          + [ {'mongos', '--logpath', '--port', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_replicaset_csrs_4(self):
        ''' mlaunch should start 4 replicaset config, 2 shards (3 nodes each), 1 mongos (CSRS) '''
        self.check_csrs()
        self.run_tool('init --sharded 2 --replicaset --config 4 --csrs')
        cmdlist = (
            [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--configsvr'} ] * 4
          + [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--shardsvr'} ] * 6
          + [ {'mongos', '--logpath', '--port', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_replicaset_csrs_mmapv1(self):
        ''' mlaunch should not change config server storage engine (CSRS) '''
        self.check_csrs()
        self.run_tool('init --sharded 2 --replicaset --csrs --storageEngine mmapv1')
        cmdlist = (
            [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--configsvr'} ]
          + [ {'mongod', '--replSet', '--dbpath', '--logpath', '--port', '--logappend', '--fork', '--storageEngine', '--shardsvr'} ] * 6
          + [ {'mongos', '--logpath', '--port', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_oplogsize_sccc(self):
        ''' mlaunch should not pass --oplogSize to config server (SCCC) '''
        self.check_sccc()
        self.run_tool('init --sharded 1 --replicaset --nodes 1 --oplogSize 19')
        cmdlist = (
            [ {'mongod', '--port', '--logpath', '--dbpath', '--configsvr', '--logappend', '--fork'} ]
          + [ {'mongod', '--port', '--replSet', '--shardsvr', '--logpath', '--dbpath', '--oplogSize', '--logappend', '--fork'} ]
          + [ {'mongos', '--port', '--logpath', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_oplogsize_csrs(self):
        ''' mlaunch should not pass --oplogSize to config server (CSRS) '''
        self.check_csrs()
        self.run_tool('init --sharded 1 --replicaset --nodes 1 --oplogSize 19 --csrs')
        cmdlist = (
            [ {'mongod', '--port', '--logpath', '--dbpath', '--configsvr', '--logappend', '--fork', '--replSet'} ]
          + [ {'mongod', '--port', '--replSet', '--shardsvr', '--logpath', '--dbpath', '--oplogSize', '--logappend', '--fork'} ]
          + [ {'mongos', '--port', '--logpath', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_two_mongos_sccc(self):
        ''' mlaunch should start 2 mongos (SCCC) '''
        self.check_sccc()
        self.run_tool('init --sharded 2 --single --config 1 --mongos 2')
        cmdlist = (
            [ {'mongod', '--port', '--logpath', '--dbpath', '--configsvr', '--logappend', '--fork'} ]
          + [ {'mongod', '--port', '--shardsvr', '--logpath', '--dbpath', '--logappend', '--fork'} ] * 2
          + [ {'mongos', '--port', '--logpath', '--configdb', '--logappend', '--fork'} ] * 2
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_two_mongos_csrs(self):
        ''' mlaunch should start 2 mongos (CSRS) '''
        self.check_csrs()
        self.run_tool('init --sharded 2 --single --config 1 --mongos 2 --csrs')
        cmdlist = (
            [ {'mongod', '--port', '--logpath', '--dbpath', '--configsvr', '--logappend', '--fork', '--replSet'} ]
          + [ {'mongod', '--port', '--shardsvr', '--logpath', '--dbpath', '--logappend', '--fork'} ] * 2
          + [ {'mongos', '--port', '--logpath', '--configdb', '--logappend', '--fork'} ] * 2
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_three_mongos_sccc(self):
        ''' mlaunch should start 3 mongos (SCCC) '''
        self.check_sccc()
        self.run_tool('init --sharded 2 --replicaset --config 3 --mongos 3')
        cmdlist = (
            [ {'mongod', '--port', '--logpath', '--dbpath', '--configsvr', '--logappend', '--fork'} ] * 3
          + [ {'mongod', '--port', '--shardsvr', '--logpath', '--dbpath', '--logappend', '--fork', '--replSet'} ] * 6
          + [ {'mongos', '--port', '--logpath', '--configdb', '--logappend', '--fork'} ] * 3
        )
        self.cmdlist_assert(cmdlist)

    def test_sharded_three_mongos_csrs(self):
        ''' mlaunch should start 3 mongos (CSRS) '''
        self.check_csrs()
        self.run_tool('init --sharded 2 --replicaset --config 3 --mongos 3 --csrs')
        cmdlist = (
            [ {'mongod', '--port', '--logpath', '--dbpath', '--configsvr', '--logappend', '--fork', '--replSet'} ] * 3
          + [ {'mongod', '--port', '--shardsvr', '--logpath', '--dbpath', '--logappend', '--fork', '--replSet'} ] * 6
          + [ {'mongos', '--port', '--logpath', '--configdb', '--logappend', '--fork'} ] * 3
        )
        self.cmdlist_assert(cmdlist)


    # 3.4 tests

    def test_default_single_3_4(self):
        ''' mlaunch should create csrs by default -- single node shards (3.4) '''
        self.check_3_4()
        self.run_tool('init --sharded 2 --single')
        cmdlist = (
            [ {'mongod', '--port', '--logpath', '--dbpath', '--configsvr', '--logappend', '--fork', '--replSet'} ]
          + [ {'mongod', '--port', '--logpath', '--dbpath', '--shardsvr', '--logappend', '--fork'} ] * 2
          + [ {'mongos', '--port', '--logpath', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_default_replicaset_3_4(self):
        ''' mlaunch should create csrs by default -- replicaset shards (3.4) '''
        self.check_3_4()
        self.run_tool('init --sharded 2 --replicaset')
        cmdlist = (
            [ {'mongod', '--port', '--logpath', '--dbpath', '--configsvr', '--logappend', '--fork', '--replSet'} ]
          + [ {'mongod', '--port', '--logpath', '--dbpath', '--shardsvr', '--logappend', '--fork', '--replSet'} ] * 6
          + [ {'mongos', '--port', '--logpath', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_default_7_replicaset_3_4(self):
        ''' mlaunch should create csrs by default -- 7 node replicaset shards (3.4) '''
        self.check_3_4()
        self.run_tool('init --sharded 2 --replicaset --nodes 7')
        cmdlist = (
            [ {'mongod', '--port', '--logpath', '--dbpath', '--configsvr', '--logappend', '--fork', '--replSet'} ]
          + [ {'mongod', '--port', '--logpath', '--dbpath', '--shardsvr', '--logappend', '--fork', '--replSet'} ] * 14
          + [ {'mongos', '--port', '--logpath', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_default_7_replicaset_5_config_3_4(self):
        ''' mlaunch should create csrs by default -- 7 node replicaset shards, 5 nodes config servers (3.4) '''
        self.check_3_4()
        self.run_tool('init --sharded 2 --replicaset --nodes 7 --config 5')
        cmdlist = (
            [ {'mongod', '--port', '--logpath', '--dbpath', '--configsvr', '--logappend', '--fork', '--replSet'} ] * 5
          + [ {'mongod', '--port', '--logpath', '--dbpath', '--shardsvr', '--logappend', '--fork', '--replSet'} ] * 14
          + [ {'mongos', '--port', '--logpath', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

    def test_default_2_replicaset_arb_4_config_2_mongos_3_4(self):
        ''' mlaunch should create csrs by default -- 2 node replicaset shards + arbiter, 4 nodes config servers, 2 mongos (3.4) '''
        self.check_3_4()
        self.run_tool('init --sharded 2 --replicaset --nodes 2 --arbiter --config 4 --mongos 2')
        cmdlist = (
            [ {'mongod', '--port', '--logpath', '--dbpath', '--configsvr', '--logappend', '--fork', '--replSet'} ] * 4
          + [ {'mongod', '--port', '--logpath', '--dbpath', '--shardsvr', '--logappend', '--fork', '--replSet'} ] * 4
          + [ {'mongod', '--port', '--logpath', '--dbpath', '--logappend', '--fork', '--replSet'} ] * 2
          + [ {'mongos', '--port', '--logpath', '--configdb', '--logappend', '--fork'} ] * 2
        )
        self.cmdlist_assert(cmdlist)

    def test_storageengine_3_4(self):
        ''' mlaunch should not pass storageEngine option to config server (3.4) '''
        self.check_3_4()
        self.run_tool('init --sharded 2 --single --storageEngine mmapv1')
        cmdlist = (
            [ {'mongod', '--port', '--logpath', '--dbpath', '--configsvr', '--logappend', '--fork', '--replSet'} ]
          + [ {'mongod', '--port', '--logpath', '--dbpath', '--shardsvr', '--logappend', '--fork', '--storageEngine'} ] * 2
          + [ {'mongos', '--port', '--logpath', '--configdb', '--logappend', '--fork'} ]
        )
        self.cmdlist_assert(cmdlist)

