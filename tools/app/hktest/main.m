/*
 * hktest: the smallest real application bundle this port can launch.
 *
 * It exists to answer one question on the phone, and nothing else: does a bundle that
 * did not come with iOS register, get an icon, start as mobile, get a data container and
 * draw?  A green window with a label is the whole of the answer; the label prints the
 * container path so that a container that was never made shows up as "(none)".
 *
 * Built with the port's own SDK (see build.sh here) and signed with ldid, no Apple
 * signature: the kernel runs with cs_enforcement_disable=1, so what it enforces is nothing.
 */
#import <UIKit/UIKit.h>

@interface HKAppDelegate : UIResponder <UIApplicationDelegate>
@property (nonatomic, strong) UIWindow *window;
@end

@implementation HKAppDelegate

- (BOOL)application:(UIApplication *)application
        didFinishLaunchingWithOptions:(NSDictionary *)launchOptions
{
	UIWindow *w = [[UIWindow alloc] initWithFrame:[UIScreen mainScreen].bounds];
	UIViewController *vc = [[UIViewController alloc] init];
	vc.view.backgroundColor = [UIColor colorWithRed:0.09 green:0.55 blue:0.33 alpha:1.0];

	UILabel *label = [[UILabel alloc] initWithFrame:CGRectInset(vc.view.bounds, 12, 60)];
	label.numberOfLines = 0;
	label.textAlignment = NSTextAlignmentLeft;
	label.textColor = [UIColor whiteColor];
	label.font = [UIFont boldSystemFontOfSize:15];

	NSString *docs = [NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES)
	    firstObject];
	NSString *probe = [docs stringByAppendingPathComponent:@"hktest-ran.txt"];
	BOOL wrote = [[NSString stringWithFormat:@"ran at %@\n", [NSDate date]]
	    writeToFile:probe atomically:YES encoding:NSUTF8StringEncoding error:NULL];

	/* This process runs as mobile, so what NSLocale says here is exactly what SpringBoard
	   saw when it drew the home screen.  The preference file is read as well: if it holds
	   Chinese while NSLocale reports English, the file is right and cfprefsd read it too
	   late (or from another domain) -- a different fix from "the file never arrived". */
	NSArray *preferred = [NSLocale preferredLanguages];
	NSDictionary *global = [NSDictionary dictionaryWithContentsOfFile:
	    @"/private/var/mobile/Library/Preferences/.GlobalPreferences.plist"];
	NSArray *inFile = global[@"AppleLanguages"];

	label.text = [NSString stringWithFormat:
	    @"HackiOS 测试应用\n\n"
	     "NSLocale.preferredLanguages:\n%@\n\n"
	     "NSLocale.currentLocale:\n%@\n\n"
	     "偏好文件 AppleLanguages:\n%@\n\n"
	     "mainBundle.preferredLocalizations:\n%@\n\n"
	     "容器: %@\n写入文件: %@",
	    [preferred componentsJoinedByString:@", "] ?: @"(nil)",
	    [[NSLocale currentLocale] localeIdentifier] ?: @"(nil)",
	    [inFile componentsJoinedByString:@", "] ?: @"(文件不存在或无此键)",
	    [[[NSBundle mainBundle] preferredLocalizations] componentsJoinedByString:@", "] ?: @"(nil)",
	    docs.length ? docs : @"(无容器)",
	    wrote ? @"成功" : @"失败"];

	[vc.view addSubview:label];
	w.rootViewController = vc;
	[w makeKeyAndVisible];
	self.window = w;
	return YES;
}

@end

int
main(int argc, char **argv)
{
	@autoreleasepool {
		return UIApplicationMain(argc, argv, nil, @"HKAppDelegate");
	}
}
