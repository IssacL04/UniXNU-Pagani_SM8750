/* OnePlus 13T, 256 GB: shrink F2FS only; never changes GPT or encryption keys. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/fs.h>
#include <mntent.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/utsname.h>
#include <unistd.h>

#define F2FS_MAGIC 0xf2f52010U
#define F2FS_IOC_RESIZE_FS _IOW(0xf5, 16, uint64_t)
#define OLD_BLOCKS UINT64_C(57685263)
#define PART_BLOCKS UINT64_C(40907796)
/* This kernel subtracts whole segments, retaining the old block-count remainder. */
#define REQUEST_BLOCKS UINT64_C(40907264)
#define RESULT_BLOCKS UINT64_C(40907535)
#define BLOCK_BYTES UINT64_C(4096)

static void fail(const char *message)
{
    fprintf(stderr, "STOP: %s\n", message);
    exit(1);
}

static uint32_t le32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static uint64_t le64(const unsigned char *p)
{
    return le32(p) | (uint64_t)le32(p + 4) << 32;
}

static uint64_t super_blocks(int fd)
{
    unsigned char copies[2][4096];
    if (pread(fd, copies, sizeof(copies), 0) != sizeof(copies))
        fail("cannot read both F2FS superblocks");
    const unsigned char *s = copies[0] + 1024;
    const unsigned char *t = copies[1] + 1024;
    if (memcmp(s, t, 3072) != 0 || le32(s) != F2FS_MAGIC ||
        le32(s + 8) != 12 || le32(s + 12) != 0 ||
        le32(s + 16) != 12 || le32(s + 20) != 9 || le32(s + 24) != 1)
        fail("unexpected F2FS geometry or disagreeing superblocks");
    return le64(s + 36);
}

int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "--self-test")) {
        const unsigned char value[] = {15, 53, 112, 3, 0, 0, 0, 0};
        assert(le64(value) == OLD_BLOCKS);
        assert(REQUEST_BLOCKS % 512 == 0);
        assert(OLD_BLOCKS - (OLD_BLOCKS - REQUEST_BLOCKS) / 512 * 512 == RESULT_BLOCKS);
        assert(RESULT_BLOCKS <= PART_BLOCKS);
        assert(OLD_BLOCKS - (OLD_BLOCKS - PART_BLOCKS / 512 * 512) / 512 * 512 > PART_BLOCKS);
        assert((UINT64_C(61705983) - 44928768 + 1) * BLOCK_BYTES == (UINT64_C(64) << 30));
        puts("SELF-TEST OK");
        return 0;
    }
    if (argc != 2 || (strcmp(argv[1], "--check") &&
        strcmp(argv[1], "--shrink") && strcmp(argv[1], "--verify"))) {
        fprintf(stderr, "Usage: %s --check | --shrink | --verify | --self-test\n", argv[0]);
        return 2;
    }
    struct utsname kernel;
    if (uname(&kernel) || !strstr(kernel.release, "-g4d611c32bedc-"))
        fail("this tool was reviewed only for kernel g4d611c32bedc");
    char rawpath[4096];
    if (!realpath("/dev/block/by-name/userdata", rawpath) || strcmp(rawpath, "/dev/block/sda15"))
        fail("userdata is not sda15");
    int raw = open(rawpath, O_RDONLY | O_CLOEXEC);
    uint64_t size = 0;
    if (raw < 0 || ioctl(raw, BLKGETSIZE64, &size) ||
        (size != OLD_BLOCKS * BLOCK_BYTES && size != PART_BLOCKS * BLOCK_BYTES))
        fail("unexpected userdata partition size");
    close(raw);

    FILE *mounts = setmntent("/proc/mounts", "r");
    if (!mounts)
        fail("cannot read mount table");
    struct mntent *entry;
    char device[4096] = "";
    while ((entry = getmntent(mounts))) {
        if (strcmp(entry->mnt_dir, "/data"))
            continue;
        if (strcmp(entry->mnt_type, "f2fs") || !hasmntopt(entry, "rw") ||
            strstr(entry->mnt_opts, "checkpoint=disable"))
            fail("/data must be mounted read-write as F2FS in decrypted TWRP");
        if ((unsigned)snprintf(device, sizeof(device), "%s", entry->mnt_fsname) >= sizeof(device))
            fail("device path too long");
        break;
    }
    endmntent(mounts);
    if (strncmp(device, "/dev/block/dm-", 14))
        fail("/data must use its decrypted device-mapper device");
    char slave[4096];
    if ((unsigned)snprintf(slave, sizeof(slave), "/sys/class/block/%s/slaves/sda15", device + 11) >= sizeof(slave) ||
        access(slave, F_OK))
        fail("decrypted device is not backed by sda15");
    int fs = open("/data", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    int block = open(device, O_RDONLY | O_CLOEXEC);
    struct stat mount_stat, block_stat;
    struct statfs info;
    if (fs < 0 || block < 0 || fstat(fs, &mount_stat) || fstat(block, &block_stat) ||
        !S_ISBLK(block_stat.st_mode) || mount_stat.st_dev != block_stat.st_rdev ||
        fstatfs(fs, &info) || (unsigned long)info.f_type != F2FS_MAGIC)
        fail("mount and block-device identity check failed");
    uint64_t before = super_blocks(block);
    if (before > size / BLOCK_BYTES)
        fail("filesystem exceeds the current partition; restore the original GPT first");
    if (before != OLD_BLOCKS && (before < RESULT_BLOCKS || before > PART_BLOCKS))
        fail("unexpected filesystem size; do not change GPT");
    printf("Device: %s; partition bytes: %" PRIu64 "\n", device, size);
    printf("F2FS blocks: %" PRIu64 "; partition limit: %" PRIu64 "\n", before, PART_BLOCKS);
    if (!strcmp(argv[1], "--check")) {
        puts(before <= PART_BLOCKS ? "ALREADY SHRUNK" : "CHECK OK; no writes performed");
        return 0;
    }
    if (!strcmp(argv[1], "--shrink") && before == OLD_BLOCKS) {
        if (size != OLD_BLOCKS * BLOCK_BYTES)
            fail("partition was shortened before the filesystem");
        puts("Shrinking F2FS through the kernel. Keep power and USB connected.");
        fflush(stdout);
        uint64_t target = REQUEST_BLOCKS;
        if (syncfs(fs) || ioctl(fs, F2FS_IOC_RESIZE_FS, &target) || syncfs(fs)) {
            fprintf(stderr, "STOP: %s; do not change GPT or blindly retry\n", strerror(errno));
            return 1;
        }
        if (super_blocks(block) != RESULT_BLOCKS)
            fail("unexpected shrink result; do not change GPT");
    }
    uint64_t after = super_blocks(block);
    if (after < RESULT_BLOCKS || after > PART_BLOCKS)
        fail("filesystem has not reached the expected size; do not change GPT");
    puts("VERIFIED: both superblocks fit within the planned userdata partition.");
    return 0;
}
