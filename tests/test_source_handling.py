import tempfile
from unittest import TestCase

from simpleais import *
import simpleais

fragmented_message_type_8 = ['!AIVDM,3,1,3,A,85NoHR1KfI99t:BHBI3sWpAoS7VHRblW8McQtR3lsFR,0*5A',
                             '!AIVDM,3,2,3,A,ApU6wWmdIeJG7p1uUhk8Tp@SVV6D=sTKh1O4fBvUcaN,0*5E',
                             '!AIVDM,3,3,3,A,j;lM8vfK0,2*34']
message_type_1 = '!ABVDM,1,1,,A,15NaEPPP01oR`R6CC?<j@gvr0<1C,0*1F'

newline = bytes("\n", "ascii")


class TestSourceHandling(TestCase):
    def test_file_source(self):
        with tempfile.NamedTemporaryFile() as file:
            for line in fragmented_message_type_8:
                file.write(bytes(line, "ascii"))
                file.write(newline)
            file.write(bytes(message_type_1, "ascii"))
            file.write(newline)
            file.flush()

            sentences = sentences_from_source(file.name)
            self.assertEqual(8, sentences.__next__().type_id())
            self.assertEqual(1, sentences.__next__().type_id())
            self.assertRaises(StopIteration, sentences.__next__)

    # TODO: figure out how to test serial and url sources effectively