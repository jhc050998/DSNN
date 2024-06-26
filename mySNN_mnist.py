import math
import time
import torch

import Dataset as Ds
import SNNLayer as mySNN


def train(sn, bs):
    gpu_num = torch.cuda.device_count()
    if gpu_num == 0:
        print("Training on cpu.")
        device = torch.device("cpu")
    else:
        print("Training on gpu.")
        device = torch.device("cuda:3")

    # Network layout
    ly1 = mySNN.SNNLayer(inCh=784, outCh=800)
    ly2 = mySNN.SNNLayer(inCh=800, outCh=10)

    # send parameters to device
    ly1.e_ts, ly1.e_tp = ly1.e_ts.to(device), ly1.e_tp.to(device)
    ly2.e_ts, ly2.e_tp = ly2.e_ts.to(device), ly2.e_tp.to(device)
    ly1.cause_mask = ly1.cause_mask.to(device)
    ly2.cause_mask = ly2.cause_mask.to(device)
    ly1.adam_m_Ets, ly1.adam_m_Etp = ly1.adam_m_Ets.to(device), ly1.adam_m_Etp.to(device)
    ly2.adam_m_Ets, ly2.adam_m_Etp = ly2.adam_m_Ets.to(device), ly2.adam_m_Etp.to(device)
    ly1.adam_v_Ets, ly1.adam_v_Etp = ly1.adam_v_Ets.to(device), ly1.adam_v_Etp.to(device)
    ly2.adam_v_Ets, ly2.adam_v_Etp = ly2.adam_v_Ets.to(device), ly2.adam_v_Etp.to(device)

    # Data prepare
    X_train, y_train = [], []  # (60000,1,28,28)
    for idx, (data, target) in enumerate(Ds.mnist_train_loader):  # read out all data in one time
        X_train, y_train = data, target
    X_train = torch.where(X_train > 0.5, 0.01, 2.3)
    # X_train = 2.9 * (1.0 - X_train)
    # X_train = torch.where(X_train >= 2.9, 2.9, X_train)
    # X_train = 8.0 * X_train
    X_train, y_train = X_train.to(device), y_train.to(device)

    # Training process
    epoch_num = 20
    lr_start, lr_end = 1e-4, 1e-6  # decaying learning rate for shifting timings
    lr_decay = (lr_end / lr_start) ** (1.0 / epoch_num)
    lr_Etp = 1e-4

    bn = int(math.ceil(sn / bs))
    loss, total_loss = 0, []
    time_start = time.time()  # time when training process start
    for epoch in range(epoch_num):  # 6000
        lr_Ets = lr_start * lr_decay ** epoch
        for bi in range(bn):  # 20
            # input data
            if (bi + 1) * bs > sn:
                data, tar = X_train[bi * bs:sn], y_train[bi * bs:sn]
            else:
                data, tar = X_train[bi * bs:(bi + 1) * bs], y_train[bi * bs:(bi + 1) * bs]
            z0 = torch.exp(1.0 - data.view(-1, 28 * 28))  # processing data (bs,1,28,28) --> (bs,784)
            tar_10 = (torch.ones(tar.size()[0], 10)*0.99).to(device)  # the prepared label
            for i in range(data.size()[0]):
                tar_10[i, tar[i]] = 0.01

            bs = z0.size()[0]

            # Forward propagation
            z1 = ly1.forward(bs, z0, dv=device)
            z2 = ly2.forward(bs, z1, dv=device)

            # Shifting Learning
            z2_lo, z_tar = torch.softmax(z2, dim=1), torch.softmax(torch.exp(tar_10), dim=1)
            delta2 = z2_lo - z_tar
            delta1 = ly2.pass_delta(bs, delta2)

            ly2.backward(bs, delta2, z1, z2, lr_Ets, lr_Etp)
            ly1.backward(bs, delta1, z0, z1, lr_Ets, lr_Etp)

            CE = -1.0 * torch.sum(torch.log(torch.clamp(z2_lo, 1e-5, 1.0)) * z_tar) / data.size()[0]
            CE_min = -1.0 * torch.sum(torch.log(torch.clamp(z_tar, 1e-5, 1.0)) * z_tar) / data.size()[0]
            loss = abs(CE - CE_min)

            if bi % 10 == 0:
                print("Current Training epoch: " + str(epoch + 1), end="\t")
                print("Progress: [" + str(bi * bs) + "/" + str(sn), end="")
                print("(%.0f %%)]" % (100.0 * bi * bs / sn), end="\t")
                print("Error: " + str(loss))
                total_loss.append(loss)
        pass
        time_epoch_end = time.time()
        print("Time consuming: %.3f s" % (time_epoch_end - time_start))
        torch.save(ly1.e_ts, "./parameters_record/SL_mnist_ets1")
        torch.save(ly1.e_tp, "./parameters_record/SL_mnist_etp1")
        torch.save(ly2.e_ts, "./parameters_record/SL_mnist_ets2")
        torch.save(ly2.e_tp, "./parameters_record/SL_mnist_etp2")
        print("Accuracy on test data: ")
        test(10000, 100)
    pass
    time_end = time.time()  # time when training process end
    print("Time consuming: %.3f s" % (time_end - time_start))

    print("loss:")
    print(torch.tensor(total_loss).size())
    print(torch.tensor(total_loss))


def test(sn, bs):
    gpu_num = torch.cuda.device_count()
    if gpu_num == 0:
        print("Testing on cpu.")
        device = torch.device("cpu")
    else:
        print("Testing on gpu.")
        device = torch.device("cuda:3")

    e_ts1 = torch.load("./parameters_record/SL_mnist_ets1").to(device)
    e_tp1 = torch.load("./parameters_record/SL_mnist_etp1").to(device)
    e_ts2 = torch.load("./parameters_record/SL_mnist_ets2").to(device)
    e_tp2 = torch.load("./parameters_record/SL_mnist_etp2").to(device)

    ly1 = mySNN.SNNLayer(784, 800, e_ts=e_ts1, e_tp=e_tp1)
    ly2 = mySNN.SNNLayer(800, 10, e_ts=e_ts2, e_tp=e_tp2)

    # Data prepare
    X_test, y_test = [], []
    for idx, (data, target) in enumerate(Ds.mnist_test_loader):
        X_test, y_test = data, target
    X_test = torch.where(X_test > 0.5, 0.01, 2.3)
    # X_test = 2.9 * (1.0 - X_test)
    # X_test = torch.where(X_test >= 2.9, math.inf, X_test)
    # X_test = 8.0 * X_test
    X_test, y_test = X_test.to(device), y_test.to(device)

    # Testing Process
    correct = 0
    bn = int(math.ceil(sn / bs))
    for bi in range(bn):
        if (bi + 1) * bs > sn:
            data, tar = X_test[bi * bs:sn], y_test[bi * bs:sn]
        else:
            data, tar = X_test[bi * bs:(bi + 1) * bs], y_test[bi * bs:(bi + 1) * bs]
        z0 = torch.exp(1.0 - data.view(-1, 28 * 28))

        # Forward propagation
        z1 = ly1.forward(bs, z0, dv=device)
        z2 = ly2.forward(bs, z1, dv=device)

        lo = torch.softmax(z2, dim=1)
        prediction = torch.argmin(lo, dim=1)
        correct += prediction.eq(tar.data).sum()
    pass
    print("Accuracy: " + str(int(correct)) + "/" + str(sn), end="")
    print("(%.3f %%)" % (100. * correct / sn))


def train_mly(sn, bs):
    gpu_num = torch.cuda.device_count()
    if gpu_num == 0:
        print("Training on cpu.")
        device = torch.device("cpu")
    else:
        print("Training on gpu.")
        device = torch.device("cuda:3")

    # Network layout
    ly1 = mySNN.SNNLayer(inCh=784, outCh=400)
    ly2 = mySNN.SNNLayer(inCh=400, outCh=400)
    ly3 = mySNN.SNNLayer(inCh=400, outCh=10)

    # send parameters to device
    ly1.e_ts, ly1.e_tp = ly1.e_ts.to(device), ly1.e_tp.to(device)
    ly2.e_ts, ly2.e_tp = ly2.e_ts.to(device), ly2.e_tp.to(device)
    ly3.e_ts, ly3.e_tp = ly3.e_ts.to(device), ly3.e_tp.to(device)
    ly1.cause_mask = ly1.cause_mask.to(device)
    ly2.cause_mask = ly2.cause_mask.to(device)
    ly3.cause_mask = ly3.cause_mask.to(device)
    ly1.adam_m_Ets, ly1.adam_m_Etp = ly1.adam_m_Ets.to(device), ly1.adam_m_Etp.to(device)
    ly2.adam_m_Ets, ly2.adam_m_Etp = ly2.adam_m_Ets.to(device), ly2.adam_m_Etp.to(device)
    ly3.adam_m_Ets, ly3.adam_m_Etp = ly3.adam_m_Ets.to(device), ly3.adam_m_Etp.to(device)
    ly1.adam_v_Ets, ly1.adam_v_Etp = ly1.adam_v_Ets.to(device), ly1.adam_v_Etp.to(device)
    ly2.adam_v_Ets, ly2.adam_v_Etp = ly2.adam_v_Ets.to(device), ly2.adam_v_Etp.to(device)
    ly3.adam_v_Ets, ly3.adam_v_Etp = ly3.adam_v_Ets.to(device), ly3.adam_v_Etp.to(device)

    # Data prepare
    X_train, y_train = [], []
    for idx, (data, target) in enumerate(Ds.mnist_train_loader):  # read out all data in one time
        X_train, y_train = data, target
    X_train = torch.where(X_train > 0.5, 0.01, 2.3)
    X_train, y_train = X_train.to(device), y_train.to(device)

    # Training process
    epoch_num = 20
    lr_start, lr_end = 1e-4, 1e-6  # decaying learning rate for shifting timings
    lr_decay = (lr_end / lr_start) ** (1.0 / epoch_num)
    lr_Etp = 1e-4

    bn = int(math.ceil(sn / bs))
    loss, total_loss = 0, []
    time_start = time.time()  # time when training process start
    for epoch in range(epoch_num):  # 6000
        lr_Ets = lr_start * lr_decay ** epoch
        for bi in range(bn):  # 20
            # input data
            if (bi + 1) * bs > sn:
                data, tar = X_train[bi * bs:sn], y_train[bi * bs:sn]
            else:
                data, tar = X_train[bi * bs:(bi + 1) * bs], y_train[bi * bs:(bi + 1) * bs]
            z0 = torch.exp(1.0 - data.view(-1, 28 * 28))  # processing data (bs,1,28,28) --> (bs,784)
            tar_10 = (torch.ones(tar.size()[0], 10)*0.99).to(device)  # the prepared label
            for i in range(data.size()[0]):
                tar_10[i, tar[i]] = 0.01

            bs = z0.size()[0]

            # Forward propagation
            z1 = ly1.forward(bs, z0, dv=device)
            z2 = ly2.forward(bs, z1, dv=device)
            z3 = ly3.forward(bs, z2, dv=device)

            # Shifting Learning
            z3_lo, z_tar = torch.softmax(z3, dim=1), torch.softmax(torch.exp(tar_10), dim=1)
            delta3 = z3_lo - z_tar
            delta2 = ly3.pass_delta(bs, delta3)
            delta1 = ly2.pass_delta(bs, delta2)

            '''# Backward propagation (Gradient)
            z3_lo, z_tar = torch.softmax(z3, dim=1), torch.softmax(torch.exp(tar_10), dim=1)
            Edd3Ex = torch.tile(torch.reshape(ly3.e_dd, [1, ly3.inCh, ly3.outCh]), [bs, 1, 1])
            delta3 = (z3_lo - z_tar) / (torch.sum(Edd3Ex * ly3.cause_mask, dim=1) - ly3.th)
            Edd2Ex = torch.tile(torch.reshape(ly2.e_dd, [1, ly2.inCh, ly2.outCh]), [bs, 1, 1])
            delta2 = ly3.pass_delta(bs, delta3) / (torch.sum(Edd2Ex * ly2.cause_mask, dim=1) - ly2.th)
            Edd1Ex = torch.tile(torch.reshape(ly1.e_dd, [1, ly1.inCh, ly1.outCh]), [bs, 1, 1])
            delta1 = ly2.pass_delta(bs, delta2) / (torch.sum(Edd1Ex * ly1.cause_mask, dim=1) - ly1.th)'''

            ly3.backward(bs, delta3, z2, z3, lr_Ets, lr_Etp)
            ly2.backward(bs, delta2, z1, z2, lr_Ets, lr_Etp)
            ly1.backward(bs, delta1, z0, z1, lr_Ets, lr_Etp)

            CE = -1.0 * torch.sum(torch.log(torch.clamp(z3_lo, 1e-5, 1.0)) * z_tar) / data.size()[0]
            CE_min = -1.0 * torch.sum(torch.log(torch.clamp(z_tar, 1e-5, 1.0)) * z_tar) / data.size()[0]
            loss = abs(CE - CE_min)

            if bi % 10 == 0:
                print("Current Training epoch: " + str(epoch + 1), end="\t")
                print("Progress: [" + str(bi * bs) + "/" + str(sn), end="")
                print("(%.0f %%)]" % (100.0 * bi * bs / sn), end="\t")
                print("Error: " + str(loss))
                total_loss.append(loss)
        pass
        time_epoch_end = time.time()
        print("Time consuming: %.3f s" % (time_epoch_end - time_start))
        torch.save(ly1.e_ts, "./parameters_record/SL_mly_mnist_ets1")
        torch.save(ly1.e_tp, "./parameters_record/SL_mly_mnist_etp1")
        torch.save(ly2.e_ts, "./parameters_record/SL_mly_mnist_ets2")
        torch.save(ly2.e_tp, "./parameters_record/SL_mly_mnist_etp2")
        torch.save(ly3.e_ts, "./parameters_record/SL_mly_mnist_ets3")
        torch.save(ly3.e_tp, "./parameters_record/SL_mly_mnist_etp3")
        print("Accuracy on test data: ")
        test(10000, 100)
    pass
    time_end = time.time()  # time when training process end
    print("Time consuming: %.3f s" % (time_end - time_start))


def test_mly(sn, bs):
    gpu_num = torch.cuda.device_count()
    if gpu_num == 0:
        print("Testing on cpu.")
        device = torch.device("cpu")
    else:
        print("Testing on gpu.")
        device = torch.device("cuda:3")

    e_ts1 = torch.load("./parameters_record/SL_mly_mnist_ets1").to(device)
    e_tp1 = torch.load("./parameters_record/SL_mly_mnist_etp1").to(device)
    e_ts2 = torch.load("./parameters_record/SL_mly_mnist_ets2").to(device)
    e_tp2 = torch.load("./parameters_record/SL_mly_mnist_etp2").to(device)
    e_ts3 = torch.load("./parameters_record/SL_mly_mnist_ets3").to(device)
    e_tp3 = torch.load("./parameters_record/SL_mly_mnist_etp3").to(device)

    ly1 = mySNN.SNNLayer(784, 400, e_ts=e_ts1, e_tp=e_tp1)
    ly2 = mySNN.SNNLayer(400, 400, e_ts=e_ts2, e_tp=e_tp2)
    ly3 = mySNN.SNNLayer(400, 10, e_ts=e_ts3, e_tp=e_tp3)

    # Data prepare
    X_test, y_test = [], []
    for idx, (data, target) in enumerate(Ds.mnist_test_loader):
        X_test, y_test = data, target
    X_test = torch.where(X_test > 0.5, 0.01, 2.3)
    X_test, y_test = X_test.to(device), y_test.to(device)

    # Testing Process
    correct = 0
    bn = int(math.ceil(sn / bs))
    for bi in range(bn):
        if (bi + 1) * bs > sn:
            data, tar = X_test[bi * bs:sn], y_test[bi * bs:sn]
        else:
            data, tar = X_test[bi * bs:(bi + 1) * bs], y_test[bi * bs:(bi + 1) * bs]
        z0 = torch.exp(1.0 - data.view(-1, 28 * 28))

        # Forward propagation
        z1 = ly1.forward(bs, z0, dv=device)
        z2 = ly2.forward(bs, z1, dv=device)
        z3 = ly3.forward(bs, z2, dv=device)

        lo = torch.softmax(z3, dim=1)
        prediction = torch.argmin(lo, dim=1)
        correct += prediction.eq(tar.data).sum()
    pass
    print("Accuracy: " + str(int(correct)) + "/" + str(sn), end="")
    print("(%.3f %%)" % (100. * correct / sn))


def main():
    train(60000, 128)
    test(10000, 100)


if __name__ == "__main__":
    main()
