# Developers Guide



## Getting Started

Setup your environment as explained in the [README]{README.md} file. Also install the optional packages.

## Workflows

Below are the workflow that are setup:

```
1. .github/workflows/01-cmake-depend-all.yml
2. .github/workflows/02-cmake-build-all.yml
3. .github/workflows/03-cmake-pkg-deb.yml
4. .github/workflows/09-github-release.yml
```

## Branching

For each modification, each developer needs to create their own repo:
```
<developer-id>/<custom name>
```

For example:
```
git checkout -b tybulut/build-automation
git push --set-upstream origin tybulut/build-automation
```

Commit messages should be simple but descriptive so that git log is readable:
```
git commit -a -m "<your message>"
```

To modify your last commit message:
```
git commit --amend
```

To compare your branch to main:
```
git diff -r main
```

To keep your branch up-to-date
```
git checkout main
git fetch origin
git pull origin

git checkout <your branch name>
git pull origin
git merge main
```

## PR Process

Create a PR for your branch online at: 
```
https://github.com/tybulut/lsmio/pulls
```

It is preferred that each PR is squashed and merged, but you can also keep your branch tidy by squashing last N commits:
```
git log # count last N commits to merge
git reset --soft HEAD~<N>
git commit -a -m "<your message>"
```

If something goes south when squashing messages in your local branch, you can revert it by:
```
git reset 'HEAD@{1}'
```

To clean-up after a PR is merged, delete your committed branch at:
```
https://github.com/tybulut/lsmio/branches
```

To clean-up after a PR is merged, clean-up your local repository:
```
git branch -a
git checkout main
git fetch origin
git pull origin
git remote update origin --prune
git branch -D <your branch name>
```

## Release Process

Create a release branch and merge it back to main with the following updates:

```
Release.latest.md # Update release messages
CMakeLists.txt # Update VERSION field
```

After the merge tag the current commit with the new VERSION value:
```
git tag v<VERSION>
git push origin --tags
```

If something goes south with tagging, you can remove the tag by:
```
git push --delete origin v0.1.6
git tag --delete v0.1.6
```

## Github Tool Setup

Install Github tools:
```
apt-get install gh
```

Setup Github tools:
```
gh auth login
```

For example, run workflow manually:
```
gh workflow run 'Create Release' --ref <your branch name>
```





