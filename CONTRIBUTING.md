# Contributing

## Initializing the repository

```shell
git clone https://android.googlesource.com/kernel/build/bootstrap
cd bootstrap
f=`git rev-parse --git-dir`/hooks/commit-msg ; mkdir -p $(dirname $f) ; curl -Lo $f https://gerrit-review.googlesource.com/tools/hooks/commit-msg ; chmod +x $f
```

## Pushing a change to code review

```shell
git push origin HEAD:refs/for/main
```
