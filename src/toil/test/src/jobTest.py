# Copyright (C) 2015-2016 Regents of the University of California
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import absolute_import, print_function
from __future__ import division
from builtins import chr
from builtins import map
from builtins import str
from builtins import range
from past.utils import old_div
import unittest
import logging
import os
import random

# Python 3 compatibility imports
from six.moves import xrange

from toil.common import Toil
from toil.leader import FailedJobsException
from toil.lib.bioio import getTempFile
from toil.job import Job, JobGraphDeadlockException, JobFunctionWrappingJob
from toil.test import ToilTest, slow

logger = logging.getLogger(__name__)

class JobTest(ToilTest):
    """
    Tests testing the job class
    """

    @classmethod
    def setUpClass(cls):
        super(JobTest, cls).setUpClass()
        logging.basicConfig(level=logging.DEBUG)


    def testResourceRequirements(self):
        """
        Runs a trivial job that ensures that default and user specified resource
        requirements are actually used.
        """
        options = Job.Runner.getDefaultOptions(self._createTempDir() + '/jobStore')
        options.clean = 'always'
        options.logLevel = 'debug'
        with Toil(options) as toil:
            toil.start(Job.wrapJobFn(checkRequirements, memory='1000M'))

    @slow
    def testStatic(self):
        """
        Create a DAG of jobs non-dynamically and run it. DAG is:
        
        A -> F
        \-------
        B -> D  \ 
         \       \
          ------- C -> E
          
        Follow on is marked by ->
        """
        outFile = getTempFile(rootDir=self._createTempDir())
        try:

            # Create the jobs
            A = Job.wrapFn(fn1Test, "A", outFile)
            B = Job.wrapFn(fn1Test, A.rv(), outFile)
            C = Job.wrapFn(fn1Test, B.rv(), outFile)
            D = Job.wrapFn(fn1Test, C.rv(), outFile)
            E = Job.wrapFn(fn1Test, D.rv(), outFile)
            F = Job.wrapFn(fn1Test, E.rv(), outFile)
            # Connect them into a workflow
            A.addChild(B)
            A.addChild(C)
            B.addChild(C)
            B.addFollowOn(E)
            C.addFollowOn(D)
            A.addFollowOn(F)

            # Create the runner for the workflow.
            options = Job.Runner.getDefaultOptions(self._getTestJobStorePath())
            options.logLevel = "INFO"
            options.retryCount = 100
            options.badWorker = 0.5
            options.badWorkerFailInterval = 0.01
            # Run the workflow, the return value being the number of failed jobs
            Job.Runner.startToil(A, options)

            # Check output
            self.assertEquals(open(outFile, 'r').readline(), "ABCDEFG")
        finally:
            os.remove(outFile)

    def testStatic2(self):
        """
        Create a DAG of jobs non-dynamically and run it. DAG is:
        
        A -> F
        \-------
        B -> D  \ 
         \       \
          ------- C -> E
          
        Follow on is marked by ->
        """
        outFile = getTempFile(rootDir=self._createTempDir())
        try:

            # Create the jobs
            A = Job.wrapFn(fn1Test, "A", outFile)
            B = Job.wrapFn(fn1Test, A.rv(), outFile)
            C = Job.wrapFn(fn1Test, B.rv(), outFile)
            D = Job.wrapFn(fn1Test, C.rv(), outFile)

            # Connect them into a workflow
            A.addChild(B)
            A.addFollowOn(C)
            C.addChild(D)

            # Create the runner for the workflow.
            options = Job.Runner.getDefaultOptions(self._getTestJobStorePath())
            options.logLevel = "INFO"
            options.retryCount = 100
            options.badWorker = 0.5
            options.badWorkerFailInterval = 0.01
            # Run the workflow, the return value being the number of failed jobs
            Job.Runner.startToil(A, options)

            # Check output
            self.assertEquals(open(outFile, 'r').readline(), "ABCDE")
        finally:
            os.remove(outFile)

    @slow
    def testTrivialDAGConsistency(self):
        options = Job.Runner.getDefaultOptions(self._createTempDir() + '/jobStore')
        options.clean = 'always'
        options.logLevel = 'debug'
        i = Job.wrapJobFn(trivialParent)
        with Toil(options) as toil:
            try:
                toil.start(i)
            except FailedJobsException:
                # we expect this exception to be raised
                pass
            else:
                self.fail()

    def testDAGConsistency(self):
        options = Job.Runner.getDefaultOptions(self._createTempDir() + '/jobStore')
        options.clean = 'always'
        i = Job.wrapJobFn(parent)
        with Toil(options) as toil:
            try:
                toil.start(i)
            except FailedJobsException:
                # we expect this exception to be raised
                pass
            else:
                self.fail()

    @slow
    def testSiblingDAGConsistency(self):
        """
        Slightly more complex case. The stranded job's predecessors are siblings instead of
        parent/child.
        """
        options = Job.Runner.getDefaultOptions(self._createTempDir() + '/jobStore')
        options.clean = 'always'
        options.logLevel = 'debug'
        i = Job.wrapJobFn(diamond)
        with Toil(options) as toil:
            try:
                toil.start(i)
            except FailedJobsException:
                # we expect this exception to be raised
                pass
            else:
                self.fail()

    def testDeadlockDetection(self):
        """
        Randomly generate job graphs with various types of cycle in them and
        check they cause an exception properly. Also check that multiple roots 
        causes a deadlock exception.
        """
        for test in range(10):
            # Make a random DAG for the set of child edges
            nodeNumber = random.choice(range(2, 20))
            childEdges = self.makeRandomDAG(nodeNumber)
            # Get an adjacency list representation and check is acyclic
            adjacencyList = self.getAdjacencyList(nodeNumber, childEdges)
            self.assertTrue(self.isAcyclic(adjacencyList))
            
            # Add in follow-on edges - these are returned as a list, and as a set of augmented
            # edges in the adjacency list
            # edges in the adjacency list
            followOnEdges = self.addRandomFollowOnEdges(adjacencyList)
            self.assertTrue(self.isAcyclic(adjacencyList))
            # Make the job graph
            rootJob = self.makeJobGraph(nodeNumber, childEdges, followOnEdges, None)
            rootJob.checkJobGraphAcylic()  # This should not throw an exception
            rootJob.checkJobGraphConnected()  # Nor this
            # Check root detection explicitly
            self.assertEquals(rootJob.getRootJobs(), {rootJob})

            # Test making multiple roots
            childEdges2 = childEdges.copy()
            childEdges2.add((nodeNumber, 1))  # This creates an extra root at "nodeNumber"
            rootJob2 = self.makeJobGraph(nodeNumber + 1, childEdges2, followOnEdges, None, False)
            try:
                rootJob2.checkJobGraphConnected()
                self.assertTrue(False)  # Multiple roots were not detected
            except JobGraphDeadlockException:
                pass  # This is the expected behaviour

            def checkChildEdgeCycleDetection(fNode, tNode):                
                childEdges.add((fNode, tNode))  # Create a cycle
                adjacencyList[fNode].add(tNode)
                self.assertTrue(not self.isAcyclic(adjacencyList))
                try:
                    self.makeJobGraph(nodeNumber, childEdges,
                                      followOnEdges, None).checkJobGraphAcylic()
                    self.assertTrue(False)  # A cycle was not detected
                except JobGraphDeadlockException:
                    pass  # This is the expected behaviour
                # Remove the edges
                childEdges.remove((fNode, tNode))
                adjacencyList[fNode].remove(tNode)
                # Check is now acyclic again
                self.makeJobGraph(nodeNumber, childEdges,
                                  followOnEdges, None, False).checkJobGraphAcylic()
                                  
            def checkFollowOnEdgeCycleDetection(fNode, tNode):
                followOnEdges.add((fNode, tNode))  # Create a cycle
                try:
                    self.makeJobGraph(nodeNumber, childEdges,
                                      followOnEdges, None, False).checkJobGraphAcylic()
                    # self.assertTrue(False) #The cycle was not detected
                except JobGraphDeadlockException:
                    pass  # This is the expected behaviour
                # Remove the edges
                followOnEdges.remove((fNode, tNode))
                # Check is now acyclic again
                self.makeJobGraph(nodeNumber, childEdges,
                                  followOnEdges, None, False).checkJobGraphAcylic()

            # Now try adding edges that create a cycle

            # Pick a random existing order relationship
            fNode, tNode = self.getRandomEdge(nodeNumber)
            while tNode not in self.reachable(fNode, adjacencyList):
                fNode, tNode = self.getRandomEdge(nodeNumber)  
            
            # Try creating a cycle of child edges
            checkChildEdgeCycleDetection(tNode, fNode)   

            # Try adding a self child edge
            node = random.choice(range(nodeNumber))
            checkChildEdgeCycleDetection(node, node)

            # Try adding a follow on edge from a descendant to an ancestor
            checkFollowOnEdgeCycleDetection(tNode, fNode)

            # Try adding a self follow on edge
            checkFollowOnEdgeCycleDetection(node, node)

            # Try adding a follow on edge between two nodes with shared descendants
            fNode, tNode = self.getRandomEdge(nodeNumber)
            if (len(self.reachable(tNode, adjacencyList)
                        .intersection(self.reachable(fNode, adjacencyList))) > 0
                and (fNode, tNode) not in childEdges and (fNode, tNode) not in followOnEdges):
                checkFollowOnEdgeCycleDetection(fNode, tNode)

    @slow
    def testNewCheckpointIsLeafVertexNonRootCase(self):
        """
        Test for issue #1465: Detection of checkpoint jobs that are not leaf vertices
        identifies leaf vertices incorrectly

        Test verification of new checkpoint jobs being leaf verticies,
        starting with the following baseline workflow:

            Parent
              |
            Child # Checkpoint=True

        """

        def createWorkflow():
            rootJob = Job.wrapJobFn(simpleJobFn, "Parent")
            childCheckpointJob = rootJob.addChildJobFn(simpleJobFn, "Child", checkpoint=True)
            return rootJob, childCheckpointJob

        self.runNewCheckpointIsLeafVertexTest(createWorkflow)

    @slow
    def testNewCheckpointIsLeafVertexRootCase(self):
        """
        Test for issue #1466: Detection of checkpoint jobs that are not leaf vertices
                              omits the workflow root job

        Test verification of a new checkpoint job being leaf vertex,
        starting with a baseline workflow of a single, root job:

            Root # Checkpoint=True

        """

        def createWorkflow():
            rootJob = Job.wrapJobFn(simpleJobFn, "Root", checkpoint=True)
            return rootJob, rootJob

        self.runNewCheckpointIsLeafVertexTest(createWorkflow)

    def testTempDir(self):
        """
        test that job.tempDir works as expected and make use of job.log for logging
        """
        message = "I love rachael price"

        options = Job.Runner.getDefaultOptions(self._getTestJobStorePath())
        with Toil(options) as workflow:
            j = sillyTestJob(message)
            j.addChildJobFn(seriousTestJob, message)
            workflow.start(j)

    def runNewCheckpointIsLeafVertexTest(self, createWorkflowFn):
        """
        Test verification that a checkpoint job is a leaf vertex using both
        valid and invalid cases.

        :param createWorkflowFn: function to create and new workflow and return a tuple of:

                                 0) the workflow root job
                                 1) a checkpoint job to test within the workflow

        """

        logger.info('Test checkpoint job that is a leaf vertex')
        self.runCheckpointVertexTest(*createWorkflowFn(),
                                     expectedException=None)

        logger.info('Test checkpoint job that is not a leaf vertex due to the presence of a service')
        self.runCheckpointVertexTest(*createWorkflowFn(),
                                     checkpointJobService=TrivialService("LeafTestService"),
                                     expectedException=JobGraphDeadlockException)

        logger.info('Test checkpoint job that is not a leaf vertex due to the presence of a child job')
        self.runCheckpointVertexTest(*createWorkflowFn(),
                                     checkpointJobChild=Job.wrapJobFn(
                                         simpleJobFn, "LeafTestChild"),
                                     expectedException=JobGraphDeadlockException)

        logger.info('Test checkpoint job that is not a leaf vertex due to the presence of a follow-on job')
        self.runCheckpointVertexTest(*createWorkflowFn(),
                                     checkpointJobFollowOn=Job.wrapJobFn(
                                         simpleJobFn,
                                         "LeafTestFollowOn"),
                                     expectedException=JobGraphDeadlockException)

    def runCheckpointVertexTest(self,
                                workflowRootJob,
                                checkpointJob,
                                checkpointJobService=None,
                                checkpointJobChild=None,
                                checkpointJobFollowOn=None,
                                expectedException=None):
        """
        Modifies the checkpoint job according to the given parameters
        then runs the workflow, checking for the expected exception, if any.
        """

        self.assertTrue(checkpointJob.checkpoint)

        if checkpointJobService is not None:
            checkpointJob.addService(checkpointJobService)
        if checkpointJobChild is not None:
            checkpointJob.addChild(checkpointJobChild)
        if checkpointJobFollowOn is not None:
            checkpointJob.addFollowOn(checkpointJobFollowOn)

        # Run the workflow and check for the expected behavior
        options = Job.Runner.getDefaultOptions(self._getTestJobStorePath())
        options.logLevel = "INFO"
        if expectedException is None:
            Job.Runner.startToil(workflowRootJob, options)
        else:
            try:
                Job.Runner.startToil(workflowRootJob, options)
                self.fail("The expected exception was not thrown")
            except expectedException as ex:
                logger.info("The expected exception was thrown: %s", repr(ex))

    @slow
    def testEvaluatingRandomDAG(self):
        """
        Randomly generate test input then check that the job graph can be 
        run successfully, using the existence of promises
        to validate the run.
        """
        jobStore = self._getTestJobStorePath()
        for test in range(5):
            # Temporary file
            tempDir = self._createTempDir(purpose='tempDir')
            # Make a random DAG for the set of child edges
            nodeNumber = random.choice(range(2, 8))
            childEdges = self.makeRandomDAG(nodeNumber)
            # Get an adjacency list representation and check is acyclic
            adjacencyList = self.getAdjacencyList(nodeNumber, childEdges)
            self.assertTrue(self.isAcyclic(adjacencyList))
            # Add in follow on edges - these are returned as a list, and as a set of augmented
            # edges in the adjacency list
            followOnEdges = self.addRandomFollowOnEdges(adjacencyList)
            self.assertTrue(self.isAcyclic(adjacencyList))
            # Make the job graph
            rootJob = self.makeJobGraph(nodeNumber, childEdges, followOnEdges, tempDir)
            # Run the job  graph
            options = Job.Runner.getDefaultOptions("%s.%i" % (jobStore, test))
            options.logLevel = "DEBUG"
            options.retryCount = 1
            options.badWorker = 0.25
            options.badWorkerFailInterval = 0.01

            # Now actually run the workflow
            try:
                with Toil(options) as toil:
                    toil.start(rootJob)
                numberOfFailedJobs = 0
            except FailedJobsException as e:
                numberOfFailedJobs = e.numberOfFailedJobs
            
            # Restart until successful or failed
            totalTrys = 1
            options.restart = True
            while numberOfFailedJobs != 0:
                try:
                    with Toil(options) as toil:
                        toil.restart()
                    numberOfFailedJobs = 0
                except FailedJobsException as e:
                    numberOfFailedJobs = e.numberOfFailedJobs
                    if totalTrys > 32: #p(fail after this many restarts) ~= 0.5**32
                        self.fail() #Exceeded a reasonable number of restarts    
                    totalTrys += 1
            
            # For each job check it created a valid output file and add the ordering
            # relationships contained within the output file to the ordering relationship,
            # so we can check they are compatible with the relationships defined by the job DAG.
            ordering = None
            for i in range(nodeNumber):
                with open(os.path.join(tempDir, str(i)), 'r') as fH:
                    ordering = list(map(int, fH.readline().split()))
                    self.assertEquals(int(ordering[-1]), i)
                    for j in ordering[:-1]:
                        adjacencyList[int(j)].add(i)
            # Check the ordering retains an acyclic graph
            if not self.isAcyclic(adjacencyList):
                print("ORDERING", ordering)
                print("CHILD EDGES", childEdges)
                print("FOLLOW ON EDGES", followOnEdges)
                print("ADJACENCY LIST", adjacencyList)
            self.assertTrue(self.isAcyclic(adjacencyList))

    @staticmethod
    def getRandomEdge(nodeNumber):
        assert nodeNumber > 1
        fNode = random.choice(range(nodeNumber - 1))
        return fNode, random.choice(range(fNode+1, nodeNumber))

    @staticmethod
    def makeRandomDAG(nodeNumber):
        """
        Makes a random dag with "nodeNumber" nodes in which all nodes are connected. Return value
        is list of edges, each of form (a, b), where a and b are integers >= 0 < nodeNumber
        referring to nodes and the edge is from a to b.
        """
        # Pick number of total edges to create
        edgeNumber = random.choice(range(nodeNumber - 1, 1 + old_div((nodeNumber * (nodeNumber - 1)), 2)))
        # Make a spanning tree of edges so that nodes are connected
        edges = set([(random.choice(range(i)), i) for i in range(1, nodeNumber)])
        # Add extra random edges until there are edgeNumber edges
        while len(edges) < edgeNumber:
            edges.add(JobTest.getRandomEdge(nodeNumber))
        return edges

    @staticmethod
    def getAdjacencyList(nodeNumber, edges):
        """
        Make adjacency list representation of edges
        """
        adjacencyList = [set() for _ in range(nodeNumber)]
        for fNode, tNode in edges:
            adjacencyList[fNode].add(tNode)
        return adjacencyList

    def reachable(self, node, adjacencyList, followOnAdjacencyList=None):
        """
        Find the set of nodes reachable from this node (including the node). Return is a set of
        integers.
        """
        visited = set()

        def dfs(fNode):
            if fNode not in visited:
                visited.add(fNode)
                list(map(dfs, adjacencyList[fNode]))
                if followOnAdjacencyList is not None:
                    list(map(dfs, followOnAdjacencyList[fNode]))

        dfs(node)
        return visited

    def addRandomFollowOnEdges(self, childAdjacencyList):
        """
        Adds random follow on edges to the graph, represented as an adjacency list. The follow on
        edges are returned as a set and their augmented edges are added to the adjacency list.
        """

        def makeAugmentedAdjacencyList():
            augmentedAdjacencyList = [childAdjacencyList[i].union(followOnAdjacencyList[i])
                                      for i in range(len(childAdjacencyList))]

            def addImpliedEdges(node, followOnEdges):
                # Let node2 be a child of node or a successor of a child of node.
                # For all node2 the following adds an edge to the augmented 
                # adjacency list from node2 to each followOn of node
                
                visited = set()

                def f(node2):
                    if node2 not in visited:
                        visited.add(node2)
                        for i in followOnEdges:
                            augmentedAdjacencyList[node2].add(i)
                        list(map(f, childAdjacencyList[node2]))
                        list(map(f, followOnAdjacencyList[node2]))

                list(map(f, childAdjacencyList[node]))

            for node in range(len(followOnAdjacencyList)):
                addImpliedEdges(node, followOnAdjacencyList[node])
            return augmentedAdjacencyList

        followOnEdges = set()
        followOnAdjacencyList = [set() for i in childAdjacencyList]
        # Loop to create the follow on edges (try 1000 times)
        while random.random() > 0.001:
            fNode, tNode = JobTest.getRandomEdge(len(childAdjacencyList))

            # Make an adjacency list including augmented edges and proposed
            # follow on edge

            # Add the new follow on edge
            followOnAdjacencyList[fNode].add(tNode)

            augmentedAdjacencyList = makeAugmentedAdjacencyList()

            # If the augmented adjacency doesn't contain a cycle then add the follow on edge to
            # the list of follow ons else remove the follow on edge from the follow on adjacency
            # list.
            if self.isAcyclic(augmentedAdjacencyList):
                followOnEdges.add((fNode, tNode))
            else:
                followOnAdjacencyList[fNode].remove(tNode)

        # Update adjacency list adding in augmented edges
        childAdjacencyList[:] = makeAugmentedAdjacencyList()[:]

        return followOnEdges

    def makeJobGraph(self, nodeNumber, childEdges, followOnEdges, outPath, addServices=True):
        """
        Converts a DAG into a job graph. childEdges and followOnEdges are the lists of child and
        followOn edges.
        """
        # Map of jobs to the list of promises they have
        jobsToPromisesMap = {}

        def makeJob(string):
            promises = []
            job = Job.wrapFn(fn2Test, promises, string,
                             None if outPath is None else os.path.join(outPath, string)) 
            jobsToPromisesMap[job] = promises
            return job

        # Make the jobs
        jobs = [makeJob(str(i)) for i in range(nodeNumber)]
        
        # Make the edges
        for fNode, tNode in childEdges:
            jobs[fNode].addChild(jobs[tNode])
        for fNode, tNode in followOnEdges:
            jobs[fNode].addFollowOn(jobs[tNode])
            
        # Map of jobs to return values
        jobsToRvs = dict([(job, job.addService(TrivialService(job.rv())) if addServices else job.rv()) for job in jobs])

        def getRandomPredecessor(job):
            predecessor = random.choice(list(job._directPredecessors))
            while random.random() > 0.5 and len(predecessor._directPredecessors) > 0:
                predecessor = random.choice(list(predecessor._directPredecessors))
            return predecessor

        # Connect up set of random promises compatible with graph                                          
        while random.random() > 0.01:
            job = random.choice(list(jobsToPromisesMap.keys()))
            promises = jobsToPromisesMap[job]
            if len(job._directPredecessors) > 0:
                predecessor = getRandomPredecessor(job)
                promises.append(jobsToRvs[predecessor])

        return jobs[0]

    def isAcyclic(self, adjacencyList):
        """
        Returns true if there are any cycles in the graph, which is represented as an adjacency
        list.
        """

        def cyclic(fNode, visited, stack):
            if fNode not in visited:
                visited.add(fNode)
                assert fNode not in stack
                stack.append(fNode)
                for tNode in adjacencyList[fNode]:
                    if cyclic(tNode, visited, stack):
                        return True
                assert stack.pop() == fNode
            return fNode in stack

        visited = set()
        for i in range(len(adjacencyList)):
            if cyclic(i, visited, []):
                return False
        return True

def simpleJobFn(job, value):
    job.fileStore.logToMaster(value)

def fn1Test(string, outputFile):
    """
    Function appends string to output file, then returns the next ascii character of the first
    character in the string, e.g. if string is "AA" returns "B".
    """

    rV = string + chr(ord(string[-1]) + 1)
    with open(outputFile, 'w') as fH:
        fH.write(rV)
    return rV


def fn2Test(pStrings, s, outputFile):
    """
    Function concatenates the strings in pStrings and s, in that order, and writes the result to
    the output file. Returns s.
    """
    with open(outputFile, 'w') as fH:
        fH.write(" ".join(pStrings) + " " + s)
    return s


def trivialParent(job):
    strandedJob = JobFunctionWrappingJob(child)
    failingJob = JobFunctionWrappingJob(errorChild)

    job.addChild(failingJob)
    job.addChild(strandedJob)
    failingJob.addChild(strandedJob)


def parent(job):
    childJob = JobFunctionWrappingJob(child)
    strandedJob = JobFunctionWrappingJob(child)
    failingJob = JobFunctionWrappingJob(errorChild)

    job.addChild(childJob)
    job.addChild(strandedJob)
    childJob.addChild(failingJob)
    failingJob.addChild(strandedJob)


def diamond(job):
    childJob = JobFunctionWrappingJob(child)
    strandedJob = JobFunctionWrappingJob(child)
    failingJob = JobFunctionWrappingJob(errorChild)

    job.addChild(childJob)
    job.addChild(failingJob)
    childJob.addChild(strandedJob)
    failingJob.addChild(strandedJob)


def child(job):
    pass


class sillyTestJob(Job):
    """
    all this job does is write a message to a tempFile
    in the tempDir (which is deleted)
    """
    def __init__(self, message):
        Job.__init__(self)
        self.message = message

    @staticmethod
    def sillify(message):
        """
        Turns "this serious help message" into "shis serious selp sessage"
        """
        return ' '.join(['s' + word if word[0] in 'aeiou' else 's' + word[1:] for word in message.split()])

    def run(self, fileStore):
        file1 = self.tempDir + 'sillyFile.txt'
        self.log('first filename is {}'.format(file1))
        file2 = self.tempDir + 'sillyFile.txt'
        self.log('second filename is {}'.format(file1))
        # make sure we get the same thing every time
        assert file1 == file2

        # write to the tempDir to be sure that everything works
        with open(file1, 'w') as fd:
            fd.write(self.sillify(self.message))


def seriousTestJob(job, message):
    # testing job.temDir for functionJobs
    with open(job.tempDir + 'seriousFile.txt', 'w') as fd:
        fd.write("The unadulterated message is:")
        fd.write(message)
    # and logging
    job.log("message has been written")


def checkRequirements(job):
    # insure default resource requirements are being set correctly
    assert job.cores is not None
    assert job.disk is not None
    assert job.preemptable is not None
    # insure user specified resource requirements are being set correctly
    assert job.memory is not None


def errorChild(job):
    raise RuntimeError('Child failure')


class TrivialService(Job.Service):
    def __init__(self, message, *args, **kwargs):
        """ Service that does nothing, used to check for deadlocks
        """
        Job.Service.__init__(self, *args, **kwargs)
        self.message = message

    def start(self, job):
        return self.message

    def stop(self, job):
        pass

    def check(self):
        pass


if __name__ == '__main__':
    unittest.main()
