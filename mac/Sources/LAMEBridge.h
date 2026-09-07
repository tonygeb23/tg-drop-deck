// The one C header the Swift side needs, and the only place LAME is named
// outside StreamOut.swift and Recorder.swift.
//
// LAME is dynamically linked and lives in Contents/Frameworks, which is what
// keeps its LGPL and this app's MIT apart. See vendor/README.md.
#import <lame/lame.h>
