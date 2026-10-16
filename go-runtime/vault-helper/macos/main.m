#import <Foundation/Foundation.h>
#import <Security/Security.h>
#include <stdio.h>
#include <string.h>

static NSString *const Identifier = @"local.meiju.mcp.vault-helper";
// A separate namespace preserves every legacy item and its ACL unchanged.
static NSString *const Service = @"meiju-mcp.vault.v1";
static BOOL Interactive = NO;
#ifdef MEIJU_VAULT_MOCK
static NSMutableDictionary<NSString *, NSData *> *MockItems;
static OSStatus MockFailure = errSecSuccess;
static NSUInteger MockCalls;
#endif

static NSDictionary *failure(NSString *code) { return @{@"ok":@NO,@"found":@NO,@"value":@"",@"code":code}; }
static NSDictionary *success(NSData *value, BOOL found) { return @{@"ok":@YES,@"found":@(found),@"value":value ? [value base64EncodedStringWithOptions:0] : @""}; }
static NSString *errorCode(OSStatus status) {
    if (status == errSecInteractionRequired || status == errSecInteractionNotAllowed || status == errSecAuthFailed || status == errSecUserCanceled || status == -25320) return @"storage_authorization_required";
    if (status == errSecDuplicateItem) return @"storage_item_exists";
    return @"storage_unavailable";
}
static OSStatus perform(NSString *action, NSString *key, NSData *input, NSData **output) {
#ifdef MEIJU_VAULT_MOCK
    MockCalls++;
    if (MockFailure != errSecSuccess) return MockFailure;
    if ([action isEqual:@"get"]) { *output=MockItems[key]; return *output ? errSecSuccess : errSecItemNotFound; }
    if ([action isEqual:@"set"]) { if(MockItems[key]) return errSecDuplicateItem; MockItems[key]=input; return errSecSuccess; }
    if(!MockItems[key]) return errSecItemNotFound;
    [MockItems removeObjectForKey:key]; return errSecSuccess;
#else
    // This setting affects only this short-lived helper's Keychain client. It
    // suppresses optional dialogs; it neither unlocks a keychain nor changes ACLs.
    OSStatus status=SecKeychainSetUserInteractionAllowed(Interactive);
    if(status != errSecSuccess) return status;
    NSMutableDictionary *query=[@{(__bridge id)kSecClass:(__bridge id)kSecClassGenericPassword,
                                 (__bridge id)kSecAttrService:Service, (__bridge id)kSecAttrAccount:key,
                                 (__bridge id)kSecAttrSynchronizable:@NO} mutableCopy];
    if ([action isEqual:@"get"]) {
        query[(__bridge id)kSecMatchLimit]=(__bridge id)kSecMatchLimitOne;
        query[(__bridge id)kSecReturnData]=@YES;
        CFTypeRef result=NULL;
        status=SecItemCopyMatching((__bridge CFDictionaryRef)query,&result);
        if(status == errSecSuccess && result) {
            if(CFGetTypeID(result)!=CFDataGetTypeID()) { CFRelease(result); return errSecDecode; }
            *output=CFBridgingRelease(result);
        } else if(result) CFRelease(result);
        return status;
    }
    if ([action isEqual:@"delete"]) return SecItemDelete((__bridge CFDictionaryRef)query);
    SecAccessRef access=NULL;
    // NULL trusts only the creating helper, NOT all applications. Never use an
    // empty trusted-app array, SecItemUpdate, or ACL/partition-list rewriting.
    status=SecAccessCreate(CFSTR("美居 MCP 本机凭据"),NULL,&access);
    if(status != errSecSuccess) return status;
    query[(__bridge id)kSecAttrAccess]=(__bridge id)access;
    query[(__bridge id)kSecValueData]=input;
    status=SecItemAdd((__bridge CFDictionaryRef)query,NULL);
    CFRelease(access);
    return status;
#endif
}
static NSDictionary *handle(id request) {
    if(![request isKindOfClass:[NSDictionary class]] || [request count]!=3) return failure(@"storage_invalid_request");
    NSString *action=request[@"action"],*key=request[@"key"],*value=request[@"value"];
    if(![action isKindOfClass:[NSString class]]||![key isKindOfClass:[NSString class]]||![value isKindOfClass:[NSString class]]) return failure(@"storage_invalid_request");
    NSRegularExpression *pattern=[NSRegularExpression regularExpressionWithPattern:@"^meiju-mcp\\.go\\.[a-f0-9]{32}\\.(encryption-key|client-app|client-codex)$" options:0 error:nil];
    NSRange match=[pattern rangeOfFirstMatchInString:key options:0 range:NSMakeRange(0,key.length)];
    if(match.location!=0||match.length!=key.length) return failure(@"storage_invalid_request");
    BOOL setting=[action isEqual:@"set"];
    if(!setting&&![action isEqual:@"get"]&&![action isEqual:@"delete"]) return failure(@"storage_invalid_request");
    NSData *input=[[NSData alloc] initWithBase64EncodedString:value options:0];
    if((setting && (value.length!=44||input.length!=32)) || (!setting&&value.length!=0)) return failure(@"storage_invalid_request");
    NSData *output=nil;OSStatus status=perform(action,key,input,&output);
    if(status==errSecItemNotFound && !setting) return success(nil,NO);
    if(status!=errSecSuccess) return failure(errorCode(status));
    if([action isEqual:@"get"]) { if(output.length!=32) return failure(@"storage_corrupt"); return success(output,YES); }
    return success(nil,NO);
}
#ifdef MEIJU_VAULT_MOCK
static int selfTest(void) {
    MockItems=[NSMutableDictionary dictionary];
    NSString *a=@"meiju-mcp.go.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.encryption-key";
    NSString *b=@"meiju-mcp.go.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.encryption-key";
    NSString *value=[[NSData dataWithBytes:"01234567890123456789012345678901" length:32] base64EncodedStringWithOptions:0];
    NSUInteger checks=0;
#define CHECK(x) do { if(!(x)) return 1; checks++; } while(0)
    NSDictionary *(^request)(NSString*,NSString*,NSString*)=^NSDictionary*(NSString *action,NSString *key,NSString *v){return handle(@{@"action":action,@"key":key,@"value":v});};
    CHECK([request(@"get",a,@"")[@"found"] isEqual:@NO]);
    CHECK([request(@"set",a,value)[@"ok"] isEqual:@YES]);
    CHECK([request(@"get",a,@"")[@"value"] isEqual:value]);
    CHECK([request(@"get",b,@"")[@"found"] isEqual:@NO]);
    CHECK([request(@"set",a,value)[@"code"] isEqual:@"storage_item_exists"]);
    CHECK([request(@"delete",a,@"")[@"ok"] isEqual:@YES]);
    CHECK([request(@"delete",a,@"")[@"ok"] isEqual:@YES]);
    CHECK([request(@"get",a,@"")[@"found"] isEqual:@NO]);
    NSUInteger before=MockCalls;
    CHECK([request(@"get",@"unrelated.password",@"")[@"ok"] isEqual:@NO]);
    CHECK([request(@"set",a,@"bad")[@"ok"] isEqual:@NO]);
    CHECK([request(@"get",a,value)[@"ok"] isEqual:@NO]);
    CHECK([handle(@{@"action":@"get",@"key":a,@"value":@"",@"extra":@YES})[@"ok"] isEqual:@NO]);
    CHECK(MockCalls==before);
    for(NSNumber *status in @[@(-25320),@(errSecInteractionNotAllowed),@(errSecAuthFailed),@(errSecUserCanceled)]) {
        MockFailure=status.intValue;
        NSDictionary *result=request(@"get",a,@"");
        CHECK([result[@"ok"] isEqual:@NO] && [result[@"code"] isEqual:@"storage_authorization_required"]);
    }
    printf("{\"mock_checks_passed\":%lu,\"native_keychain_calls\":0}\n",(unsigned long)checks);return 0;
}
#endif
int main(int argc,const char *argv[]) { @autoreleasepool {
    if(argc==2 && strcmp(argv[1],"--identity")==0) { printf("{\"identifier\":\"local.meiju.mcp.vault-helper\",\"protocol\":1,\"backend\":\"meiju-vault-v1\"}\n");return 0; }
#ifdef MEIJU_VAULT_MOCK
    if(argc==2 && strcmp(argv[1],"--self-test")==0) return selfTest();
    MockItems=[NSMutableDictionary dictionary];
#endif
    if(argc==2 && strcmp(argv[1],"--authorize")==0) Interactive=YES;
    else if(argc!=1) return 2;
    unsigned char bytes[4097];size_t n=fread(bytes,1,sizeof(bytes),stdin);
    NSDictionary *response;
    if(n>4096) response=failure(@"storage_invalid_request");
    else { NSData *data=[NSData dataWithBytes:bytes length:n];id request=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];response=handle(request); }
    NSData *json=[NSJSONSerialization dataWithJSONObject:response options:0 error:nil];
    fwrite(json.bytes,1,json.length,stdout);fputc('\n',stdout);return 0;
} }
