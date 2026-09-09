// Disposable M0 test driver. No production CLI or filesystem sandbox.
#include <git2.h>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

template<class T, void (*Free)(T*)> using Handle = std::unique_ptr<T, decltype(Free)>;
using Repo = Handle<git_repository, git_repository_free>;
using Commit = Handle<git_commit, git_commit_free>;
using Index = Handle<git_index, git_index_free>;
using Tree = Handle<git_tree, git_tree_free>;
using Ref = Handle<git_reference, git_reference_free>;

void check(int result) {
    if (result < 0) {
        const git_error* error = git_error_last();
        throw std::runtime_error(error ? error->message : "libgit2 failure");
    }
}
std::string hex(const git_oid* oid) {
    char text[GIT_OID_HEXSZ + 1];
    git_oid_tostr(text, sizeof(text), oid);
    return text;
}
Commit commit_at(git_repository* repo, const char* revision) {
    git_object* object = nullptr;
    check(git_revparse_single(&object, repo, revision));
    Handle<git_object, git_object_free> obj(object, git_object_free);
    git_commit* commit = nullptr;
    check(git_commit_lookup(&commit, repo, git_object_id(object)));
    return Commit(commit, git_commit_free);
}
struct Auth { bool attempted = false; };
int credentials(git_credential** out, const char*, const char*, unsigned int allowed, void* payload) {
    auto* auth = static_cast<Auth*>(payload);
    const char* user = std::getenv("M0_AUTH_USER");
    const char* password = std::getenv("M0_AUTH_PASSWORD");
    if (auth->attempted || !user || !password || !(allowed & GIT_CREDENTIAL_USERPASS_PLAINTEXT))
        return GIT_EAUTH;
    auth->attempted = true;
    return git_credential_userpass_plaintext_new(out, user, password);
}
int run(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "version") {
        int major, minor, patch;
        git_libgit2_version(&major, &minor, &patch);
        std::cout << major << '.' << minor << '.' << patch << " features=" << git_libgit2_features() << '\n';
        return 0;
    }
    if (argc < 3) throw std::runtime_error("command and disposable repository required");
    std::string command = argv[1];
    git_repository* raw_repo = nullptr;
    if (command == "clone") {
        if (argc != 4) throw std::runtime_error("clone destination source");
        check(git_clone(&raw_repo, argv[3], argv[2], nullptr));
        Repo repo(raw_repo, git_repository_free);
        return 0;
    }
    check(git_repository_open(&raw_repo, argv[2]));
    Repo repo(raw_repo, git_repository_free);
    if (command == "head") {
        auto head = commit_at(repo.get(), "HEAD");
        std::cout << hex(git_commit_id(head.get())) << '\n';
    } else if (command == "commit" || command == "prepare") {
        if (argc < 6) throw std::runtime_error("commit/prepare repo message second-parent-or-dash paths...");
        auto first = commit_at(repo.get(), "HEAD");
        git_index* raw_index = nullptr;
        check(git_repository_index(&raw_index, repo.get()));
        Index index(raw_index, git_index_free);
        for (int i = 5; i < argc; ++i) {
            if (std::filesystem::exists(std::filesystem::path(argv[2]) / argv[i]))
                check(git_index_add_bypath(index.get(), argv[i]));
            else
                check(git_index_remove_bypath(index.get(), argv[i]));
        }
        check(git_index_write(index.get()));
        git_oid tree_id, commit_id;
        check(git_index_write_tree(&tree_id, index.get()));
        git_tree* raw_tree = nullptr;
        check(git_tree_lookup(&raw_tree, repo.get(), &tree_id));
        Tree tree(raw_tree, git_tree_free);
        git_signature* raw_signature = nullptr;
        check(git_signature_now(&raw_signature, "M0 Comparison", "comparison@example.invalid"));
        Handle<git_signature, git_signature_free> signature(raw_signature, git_signature_free);
        Commit second(nullptr, git_commit_free);
        std::vector<const git_commit*> parents{first.get()};
        if (std::string(argv[4]) != "-") {
            second = commit_at(repo.get(), argv[4]);
            parents.push_back(second.get());
        }
        check(git_commit_create(&commit_id, repo.get(), command == "commit" ? "HEAD" : nullptr,
                               signature.get(), signature.get(), nullptr, argv[3], tree.get(),
                               parents.size(), parents.data()));
        if (command == "commit") check(git_repository_state_cleanup(repo.get()));
        std::cout << hex(&commit_id) << '\n';
    } else if (command == "branch") {
        if (argc != 4) throw std::runtime_error("branch repo name");
        auto head = commit_at(repo.get(), "HEAD");
        git_reference* raw_ref = nullptr;
        check(git_branch_create(&raw_ref, repo.get(), argv[3], head.get(), 0));
        Ref ref(raw_ref, git_reference_free);
    } else if (command == "fetch") {
        if (argc != 4) throw std::runtime_error("fetch repo source");
        git_remote* raw_remote = nullptr;
        check(git_remote_create_anonymous(&raw_remote, repo.get(), argv[3]));
        Handle<git_remote, git_remote_free> remote(raw_remote, git_remote_free);
        git_fetch_options options;
        check(git_fetch_options_init(&options, GIT_FETCH_OPTIONS_VERSION));
        Auth auth;
        options.callbacks.credentials = credentials;
        options.callbacks.payload = &auth;
        char spec[] = "+refs/heads/main:refs/remotes/probe/main";
        char* specs[] = {spec};
        git_strarray refspecs{specs, 1};
        check(git_remote_fetch(remote.get(), &refspecs, &options, "M0 fetch"));
    } else if (command == "merge") {
        if (argc != 4) throw std::runtime_error("merge repo revision");
        git_status_list* raw_status = nullptr;
        check(git_status_list_new(&raw_status, repo.get(), nullptr));
        Handle<git_status_list, git_status_list_free> status(raw_status, git_status_list_free);
        if (git_status_list_entrycount(status.get())) throw std::runtime_error("merge requires clean input");
        auto other = commit_at(repo.get(), argv[3]);
        git_annotated_commit* raw_other = nullptr;
        check(git_annotated_commit_lookup(&raw_other, repo.get(), git_commit_id(other.get())));
        Handle<git_annotated_commit, git_annotated_commit_free> annotated(raw_other, git_annotated_commit_free);
        const git_annotated_commit* heads[] = {annotated.get()};
        git_checkout_options options;
        check(git_checkout_options_init(&options, GIT_CHECKOUT_OPTIONS_VERSION));
        options.checkout_strategy = GIT_CHECKOUT_SAFE | GIT_CHECKOUT_ALLOW_CONFLICTS;
        check(git_merge(repo.get(), heads, 1, nullptr, &options));
        git_index* raw_index = nullptr;
        check(git_repository_index(&raw_index, repo.get()));
        Index index(raw_index, git_index_free);
        return git_index_has_conflicts(index.get()) ? 3 : 0;
    } else if (command == "abort") {
        if (git_repository_state(repo.get()) != GIT_REPOSITORY_STATE_MERGE)
            throw std::runtime_error("No merge to abort");
        auto head = commit_at(repo.get(), "HEAD");
        check(git_reset(repo.get(), reinterpret_cast<git_object*>(head.get()), GIT_RESET_HARD, nullptr));
        check(git_repository_state_cleanup(repo.get()));
    } else if (command == "cas") {
        if (argc != 6) throw std::runtime_error("cas repo ref candidate expected");
        git_oid candidate, expected;
        check(git_oid_fromstr(&candidate, argv[4]));
        check(git_oid_fromstr(&expected, argv[5]));
        git_reference* raw_ref = nullptr;
        check(git_reference_create_matching(&raw_ref, repo.get(), argv[3], &candidate, 1, &expected, "M0 CAS"));
        Ref ref(raw_ref, git_reference_free);
    } else throw std::runtime_error("Unknown command");
    return 0;
}
int main(int argc, char** argv) {
    git_libgit2_init();
    int result;
    try { result = run(argc, argv); }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; result = 1; }
    git_libgit2_shutdown();
    return result;
}
