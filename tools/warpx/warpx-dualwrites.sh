#!/bin/sh -x

cd run-001/
grep LSMIOStream::open out.txt | grep checkpoint/000000 | awk -F"filename: " '{ print $2 }' | sort | uniq > ~/file-lsmio.txt
find ./checkpoint/000000 -type f | grep -v lsmio | sort | uniq > ~/file-posix.txt
diff -ruPN ~/file-posix.txt ~/file-lsmio.txt 

ls -la 000000/*/Level_0/*00*
grep 'LSMIOStream::write' ../../laser_ion/run-001/out.txt | grep 000008 | grep _00 | awk '{ print $6" "$7" "$8" "$9 }' | sort


