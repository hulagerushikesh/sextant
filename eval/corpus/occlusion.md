# Handling Occlusion

Occlusion is the dominant source of tracking error. Almost every identity switch
happens because an object was hidden and the tracker had to guess what happened
while it could not see.

## Kinds of occlusion

**Partial** occlusion leaves a detection, but a weaker and geometrically wrong
one — the visible fragment's box, not the object's. **Full** occlusion removes
the detection entirely. **Inter-object** occlusion, where the occluder is
another tracked object, is the hardest, because both objects are moving and
their boxes overlap heavily just before and after.

## Surviving it

Three mechanisms compound. Coasting keeps the track alive on prediction while
`max_age` has not expired. Two-stage association recovers the weak detection a
partially occluded object still produces. Appearance embeddings let a
re-emerging object be matched to its old identity even after the motion estimate
has drifted.

## Detecting it

An abrupt drop in detection confidence together with a rising IoU against
another track is a reliable signal that one object is passing behind another.
Some pipelines freeze the appearance model during suspected occlusion, so the
gallery is not poisoned with pixels belonging to the occluder.

That last point is easy to miss and expensive: an appearance embedding updated
while the object is half-hidden encodes the wrong object, and the track will
then confidently re-associate to the wrong identity afterwards.
