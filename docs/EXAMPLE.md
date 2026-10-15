# A large real tree

The node tree from the Blender Stack Exchange question
[How can I better structure my node tree and make it easier for others to understand?](https://blender.stackexchange.com/questions/266334/how-can-i-better-structure-my-node-tree-and-make-it-easier-for-others-to-underst)
by [quellenform](https://blender.stackexchange.com/users/145249/quellenform): a deliberately
tangled Geometry Nodes tree ("GN.Psychologist" in its .blend file), whose answers collect advice
on readable node trees.

The tree has 115 nodes. It was opened in Blender 5.2 and sorted with Sort Current Tree, every
rule on, at UI scale 1.4: the sort takes about 30 seconds, and the result has 124 nodes (9 of
them copies of input nodes) and 238 reroutes. Both images are captured with Capture Tree at half
zoom.

## Before

![The tree before sorting](images/stackexchange-before.png)

## After

![The tree after sorting with nodefmt](images/stackexchange-after.png)

## Credits

The node tree is the work of quellenform, shared on Blender Stack Exchange under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). The two screenshots on this page
show that tree (the second one rearranged by nodefmt) and are shared under the same license.
